import argparse
import asyncio
import fcntl
import json
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig, ModelAPI, ModelCall, ModelOutput, ModelUsage

from ...codex_budget import BudgetStop, reserve
from . import codex_environment

MODEL = "gpt-6.2-astra"
STUDY_HOME = Path.home() / ".local/state/livenerf-codex/instrument"
CLI_VERSION = "codex-cli 0.169.1"
PROBE_RESERVATION = 2
DISABLED_FEATURES = ("shell_tool", "hooks", "multi_agent", "multi_agent_v2", "skill_search", "apps", "plugins")


class InstrumentError(RuntimeError):
    pass


class AppServer:
    def __init__(self, process):
        self.process = process
        self.request_id = 0

    async def send(self, message):
        self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        await self.process.stdin.drain()

    async def receive(self):
        line = await self.process.stdout.readline()
        if not line:
            raise InstrumentError("Codex closed the app-server connection")
        message = json.loads(line)
        if "id" in message and "method" in message:
            raise InstrumentError(f"Unexpected server request: {message['method']}")
        return message

    async def request(self, method, params, events=None):
        self.request_id += 1
        await self.send({"id": self.request_id, "method": method, "params": params})
        while True:
            message = await self.receive()
            if message.get("id") == self.request_id:
                if "error" in message:
                    raise InstrumentError(f"Codex rejected {method} (code {message['error'].get('code')})")
                return message["result"]
            if events is not None:
                events.append(message)
            elif message.get("method") in {"error", "model/rerouted"}:
                validate_event(message)


@asynccontextmanager
async def app_server():
    overrides = [
        '-c', 'forced_login_method="chatgpt"',
        '-c', 'model_provider="openai"',
        '-c', 'project_doc_max_bytes=0',
        '-c', 'web_search="disabled"',
    ]
    for feature in DISABLED_FEATURES:
        overrides.extend(("-c", f"features.{feature}=false"))
    STUDY_HOME.mkdir(parents=True, mode=0o700, exist_ok=True)
    env = {**codex_environment(), "CODEX_HOME": str(STUDY_HOME)}
    with TemporaryDirectory(prefix="livenerf-instrument-") as cwd:
        process = await asyncio.create_subprocess_exec(
            "codex", *overrides, "app-server",
            cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            server = AppServer(process)
            await server.request("initialize", {
                "clientInfo": {"name": "livenerf", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            await server.send({"method": "initialized"})
            yield server, cwd
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


async def start_thread(server, cwd, system, model=MODEL):
    config = (await server.request("config/read", {"cwd": cwd}))["config"]
    if (
        config.get("mcp_servers") or config.get("model_provider") != "openai"
        or config.get("web_search") != "disabled"
        or any((config.get("features") or {}).get(feature) is not False for feature in DISABLED_FEATURES)
    ):
        raise InstrumentError("Effective Codex configuration includes MCP or an unexpected provider")
    result = await server.request("thread/start", {
        "cwd": cwd, "model": model, "modelProvider": "openai", "baseInstructions": system,
        "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": True,
        "allowProviderModelFallback": False, "dynamicTools": [],
    })
    sandbox = result.get("sandbox", {})
    if (
        result.get("model") != model or result.get("modelProvider") != "openai"
        or result.get("approvalPolicy") != "never" or sandbox.get("type") != "readOnly"
        or result.get("instructionSources")
    ):
        raise InstrumentError("Codex did not confirm the requested isolated thread configuration")
    return result["thread"]["id"]


async def preflight():
    async with asyncio.timeout(30), app_server() as (server, cwd):
        await start_thread(server, cwd, "Return only the requested answer.")


def validate_event(message):
    method = message.get("method")
    params = message.get("params", {})
    if method == "model/rerouted":
        raise InstrumentError("[fallback] Codex reported a model reroute")
    if method == "error":
        marker = "[retried] " if params.get("willRetry") else ""
        raise InstrumentError(f"{marker}Codex reported a turn error")
    if method not in {"item/started", "item/completed"}:
        return
    item = params["item"]
    if item["type"] not in {"userMessage", "reasoning", "agentMessage"}:
        raise InstrumentError("Codex reported an unexpected non-text item")
    if (item.get("moderation") or {}).get("moderated"):
        raise InstrumentError("[refusal] Codex marked the answer as moderated")


async def text_turn(server, thread_id, prompt, effort):
    events = []
    result = await server.request("turn/start", {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt, "text_elements": []}],
        "effort": effort,
    }, events)
    turn_id = result["turn"]["id"]
    usage = None
    answers = []
    while True:
        event = events.pop(0) if events else await server.receive()
        validate_event(event)
        method = event.get("method")
        params = event.get("params", {})
        if method == "thread/tokenUsage/updated" and params.get("turnId") == turn_id:
            usage = params["tokenUsage"]["total"]
        if method == "item/completed" and params.get("turnId") == turn_id:
            item = params["item"]
            if item["type"] == "agentMessage":
                answers.append(item["text"])
        if method == "turn/completed" and params["turn"]["id"] == turn_id:
            if params["turn"]["status"] != "completed" or len(answers) != 1 or not answers[0].strip() or usage is None:
                raise InstrumentError("Expected one completed text answer and token counts")
            return answers[0], usage


def check_version():
    version = subprocess.check_output(["codex", "--version"], env=codex_environment(), text=True, timeout=15).strip()
    if version != CLI_VERSION:
        raise InstrumentError(f"Expected {CLI_VERSION}, got {version}")
    return version


class DriftCodexAPI(ModelAPI):
    def __init__(self, model_name, base_url=None, api_key=None, config=GenerateConfig()):
        if base_url or api_key or model_name not in {MODEL, "gpt-6.2-sol"}:
            raise ValueError("Select a study model using the dedicated Codex ChatGPT sign-in")
        super().__init__(model_name, config=config)
        self.cli_version = check_version()

    async def generate(self, input, tools, tool_choice, config):
        system = [message.content for message in input if isinstance(message, ChatMessageSystem)]
        user = [message.content for message in input if isinstance(message, ChatMessageUser)]
        if tools or len(system) != 1 or len(user) != 1 or len(input) != 2 or not all(
            isinstance(text, str) for text in system + user
        ):
            raise ValueError("Expected one system and one user text message without tools")
        if config.effort not in {"low", "medium", "high"}:
            raise ValueError("Select an explicit study reasoning effort")
        request = {
            "model": self.model_name, "effort": config.effort, "cli_version": self.cli_version,
            "system": system[0], "prompt": user[0],
        }
        started = time.monotonic()
        try:
            async with asyncio.timeout(180), app_server() as (server, cwd):
                thread_id = await start_thread(server, cwd, system[0], self.model_name)
                answer, usage = await text_turn(server, thread_id, user[0], config.effort)
            tokens = ModelUsage(
                input_tokens=usage["inputTokens"], input_tokens_cache_read=usage["cachedInputTokens"],
                output_tokens=usage["outputTokens"], total_tokens=usage["totalTokens"],
            )
        except (InstrumentError, TimeoutError, OSError, KeyError, ValueError) as error:
            return error, ModelCall.create(request=request, response={"error": str(error)}, time=time.monotonic() - started)

        elapsed = time.monotonic() - started
        output = ModelOutput.from_content(model=self.model_name, content=answer)
        output.usage = tokens
        output.time = elapsed
        return output, ModelCall.create(request=request, response={"answer": answer, "usage": usage}, time=elapsed)


async def probe():
    async with asyncio.timeout(120), app_server() as (server, cwd):
        thread_id = await start_thread(server, cwd, "Return only the requested answer.")
        with (STUDY_HOME.parent / ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise BudgetStop("The daily monitor is running") from error
            limits = (await server.request("account/rateLimits/read", {}))["rateLimits"]
            used, reserved = reserve(STUDY_HOME.parent / "study-budget.json", limits, PROBE_RESERVATION)
            print(f"Weekly meter {used}%. Study points conservatively reserved: {reserved}.", flush=True)
            answer, _ = await text_turn(
                server, thread_id, "Reply with <answer>7</answer> and nothing else.", "high"
            )
            if answer != "<answer>7</answer>":
                raise InstrumentError("Probe did not return the expected answer")
            print("One text response, token usage and a completed turn verified.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Check the Codex study instrument without submitting a prompt.")
    parser.add_argument("--probe", action="store_true", help="Reserve quota and submit one test question")
    args = parser.parse_args()
    try:
        check_version()
        asyncio.run(probe() if args.probe else preflight())
    except (InstrumentError, BudgetStop, TimeoutError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Codex instrument check failed: {error}\n")
    if not args.probe:
        print("Codex confirmed a read-only ephemeral Astra thread. No turn was submitted.")


if __name__ == "__main__":
    main()
