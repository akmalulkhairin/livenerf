import asyncio
import json
import os
import subprocess
import tempfile
import time

from inspect_ai.model import (
    ChatMessageSystem, ChatMessageUser, GenerateConfig, ModelAPI, ModelCall, ModelOutput, ModelUsage,
)

CODEX_ENV = ("HOME", "PATH", "CODEX_HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "LANG")


def codex_environment():
    return {key: os.environ[key] for key in CODEX_ENV if key in os.environ}


class CodexAPI(ModelAPI):
    def __init__(self, model_name, base_url=None, api_key=None, config=GenerateConfig(), *,
                 expect_cli_version=None, timeout=180):
        if model_name not in {"gpt-6.2-astra", "gpt-6.2-sol"}:
            raise ValueError(f"Unsupported Codex benchmark model: {model_name}")
        if base_url or api_key:
            raise ValueError("The Codex benchmark uses ChatGPT login.")
        super().__init__(model_name, config=config)
        self.timeout = float(timeout)
        self.cli_version = subprocess.check_output(["codex", "--version"], text=True).strip()
        if expect_cli_version and self.cli_version != expect_cli_version:
            raise ValueError(f"Expected {expect_cli_version}, found {self.cli_version}")

    async def generate(self, input, tools, tool_choice, config):
        if tools or any(not isinstance(message, (ChatMessageSystem, ChatMessageUser))
                        or not isinstance(message.content, str) for message in input):
            raise ValueError("The Codex benchmark accepts single-turn text without tools.")
        if sum(isinstance(message, ChatMessageUser) for message in input) != 1:
            raise ValueError("The Codex benchmark requires one user message.")
        effort = config.effort
        if effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("Set an explicit reasoning effort with --effort.")

        prompt = "\n\n".join(message.content for message in input)
        request = {"model": self.model_name, "effort": effort, "prompt": prompt,
                   "cli_version": self.cli_version}
        command = [
            "codex", "-a", "never", "exec", "--ignore-user-config", "--ignore-rules",
            "--disable", "shell_tool", "--disable", "hooks", "--disable", "multi_agent",
            "--disable", "skill_search", "-c", 'web_search="disabled"',
            "-c", 'forced_login_method="chatgpt"', "-c", f'model_reasoning_effort="{effort}"',
            "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check",
            "--json", "-m", self.model_name, "-",
        ]
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="livenerf-codex-") as cwd:
            process = await asyncio.create_subprocess_exec(
                *command, cwd=cwd, env=codex_environment(), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(prompt.encode()), self.timeout)
            except (TimeoutError, asyncio.CancelledError):
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise

        elapsed = time.monotonic() - start
        response = {"stdout": stdout.decode(errors="replace"), "stderr": stderr.decode(errors="replace"),
                    "returncode": process.returncode}
        call = ModelCall.create(request=request, response=response, time=elapsed)
        try:
            events = [json.loads(line) for line in response["stdout"].splitlines()]
            answer, usage = read_turn(events, process.returncode)
            usage = ModelUsage(
                input_tokens=usage["input_tokens"],
                input_tokens_cache_read=usage.get("cached_input_tokens"),
                output_tokens=usage["output_tokens"],
                total_tokens=usage["input_tokens"] + usage["output_tokens"],
            )
        except (ValueError, KeyError, TypeError) as error:
            return ValueError(f"Codex turn failed: {error}"), call

        output = ModelOutput.from_content(model=self.model_name, content=answer)
        output.time = elapsed
        output.usage = usage
        return output, call


def read_turn(events, returncode):
    turns = [event for event in events if event["type"] == "turn.completed"]
    items = [event["item"] for event in events if event["type"] == "item.completed"]
    answers = [item["text"] for item in items if item["type"] == "agent_message"]
    if (returncode or len(turns) != 1 or len(answers) != 1 or not answers[0].strip()
            or any(event["type"] in {"error", "turn.failed"} for event in events)
            or any(item["type"] not in {"agent_message", "reasoning"} for item in items)):
        raise ValueError(f"Expected one successful text-only turn (Codex exit {returncode}).")
    return answers[0], turns[0]["usage"]
