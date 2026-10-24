"""Helper script to inspect recent turns stored in the app_turn table."""

import asyncio
import json
from backend.database.postgres.client import PostgresClient
from backend.database.search_config import SearchSettings


async def main() -> None:
    client = PostgresClient(SearchSettings())
    await client.open()
    try:
        async with client.transaction() as conn:
            rows = await conn.fetch(
                "SELECT run_id, session_id, state, created_at FROM app_turn ORDER BY created_at DESC LIMIT 5;"
            )
            print(f"Total turns fetched: {len(rows)}\n")
            for idx, r in enumerate(rows, 1):
                state = json.loads(r["state"]) if isinstance(r["state"], str) else r["state"]
                user_msg = state.get("user_message", "")
                status = state.get("termination", {}).get("status", "UNKNOWN")
                obs = [
                    o.get("component")
                    for o in state.get("execution", {}).get("observations", [])
                ]
                evidence_graph = state.get("evidence", {}).get("graph", [])
                nodes_found = []
                for ev in evidence_graph:
                    for node in ev.get("graph_nodes", []):
                        nodes_found.append(node)

                print(f"[{idx}] Run ID: {r['run_id']}")
                print(f"    Session ID: {r['session_id']}")
                print(f"    User Query: '{user_msg}'")
                print(f"    Status: {status}")
                print(f"    Observed Subagents: {obs}")
                print(f"    Graph Nodes Extracted: {len(nodes_found)}")
                if nodes_found:
                    print(f"    Sample Node: {nodes_found[0]}")
                print("-" * 60)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
