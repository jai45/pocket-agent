"""Facts the harness passes to tools, never chosen by the model.

Which chat a request came from is known for certain by the bot. Passing it
directly means Claude can't get it wrong, and text injected by a web page
can't steer a tool into another chat's data.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolContext:
    chat_id: int
