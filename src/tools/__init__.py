"""Read-only tools that wrap services for LLM agents (ARCHITECTURE §4.3)."""
from src.tools.base import Tool, tool_registry
from src.tools.comp import CompResult, SearchCompTool
from src.tools.company import CompanyBrief, FetchCompanyBriefTool
from src.tools.repost import CheckRepostTool, RepostResult

__all__ = [
    "Tool", "tool_registry",
    "SearchCompTool", "CompResult",
    "FetchCompanyBriefTool", "CompanyBrief",
    "CheckRepostTool", "RepostResult",
    "default_tools",
]


def default_tools() -> list[Tool]:
    """The standard read-only tool set an agent is given."""
    return [SearchCompTool(), FetchCompanyBriefTool(), CheckRepostTool()]
