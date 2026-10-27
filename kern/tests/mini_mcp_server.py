"""Kleiner echter MCP-Testserver (stdio) für die Tests des MCP-Hubs."""

from mcp.server.mcpserver import MCPServer

server = MCPServer("mini-test")


@server.tool()
def addieren(a: int, b: int) -> str:
    """Addiert zwei Zahlen."""
    return str(a + b)


@server.tool()
def echo(text: str) -> str:
    """Gibt den Text zurück."""
    return f"Echo: {text}"


@server.tool()
def delete_item(item_id: str) -> str:
    """Löscht ein Element (nur zum Testen der Risikoeinstufung)."""
    return f"gelöscht: {item_id}"


@server.tool()
def fehler_werfen() -> str:
    """Wirft immer einen Fehler."""
    raise ValueError("absichtlicher Fehler")


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run("stdio")
