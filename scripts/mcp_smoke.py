import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CAPTURE = sys.argv[1]
ENV = dict(os.environ)
ENV["PYTHONPATH"] = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src")
)


async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rdebug_mcp.server"],
        env=ENV,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print("tools:", names)
            assert names == ["debug_pixel", "diff_pixel", "trace_pixel",
                             "trace_resource"], names

            result = await session.call_tool(
                "trace_pixel",
                {"capture": CAPTURE, "x": 320, "y": 240, "max_draws": 4},
            )
            payload = json.loads(result.content[0].text)
            print("trace_pixel:", payload["summary"]["target"],
                  "nodes:", len(payload["nodes"]),
                  "evidence:", payload["summary"]["evidence"][0]["id"])

            result = await session.call_tool(
                "diff_pixel",
                {"capture": CAPTURE, "a_x": 320, "a_y": 240, "b_x": 10, "b_y": 10},
            )
            payload = json.loads(result.content[0].text)
            print("diff_pixel:", payload["comparison"],
                  "first:", payload["firstDivergence"]["layer"])

            result = await session.call_tool(
                "trace_resource",
                {"capture": CAPTURE, "resource": "ResourceId::47"},
            )
            payload = json.loads(result.content[0].text)
            print("trace_resource writers:",
                  [(w["eventId"], w["usage"]) for w in payload["writers"]])

            result = await session.call_tool(
                "debug_pixel",
                {"capture": CAPTURE, "x": 320, "y": 240, "max_steps": 512},
            )
            payload = json.loads(result.content[0].text)
            print("debug_pixel:", payload["eventId"],
                  "steps:", payload["stepCount"])

            print("MCP SMOKE OK")


asyncio.run(main())
