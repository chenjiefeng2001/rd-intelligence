import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(capture, tool, args_json, out_path):
    args = json.loads(args_json) if args_json else {}
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "src")
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "rdebug_mcp.server"], env=env
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            t0 = time.perf_counter()
            result = await session.call_tool(tool, args)
            latency = round((time.perf_counter() - t0) * 1000.0, 1)
            text = result.content[0].text
            if out_path:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text)
            payload = json.loads(text)
            print(json.dumps({
                "tool": tool,
                "latencyMs": latency,
                "keys": list(payload.keys()),
                "error": payload.get("error"),
                "saved": out_path,
            }, ensure_ascii=False))


if __name__ == "__main__":
    args_path = sys.argv[3]
    args_json = "{}" if args_path == "-" else open(args_path, encoding="utf-8").read()
    asyncio.run(run(sys.argv[1], sys.argv[2], args_json, sys.argv[4]))
