"""Obsidian-compatible knowledge vault helpers."""

from .entries import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    VersionSnapshot,
    extract_wiki_links,
)
from .permissions import AccessMode, AgentRole, PermissionManager
from .project_permissions import (
    ProjectAuthorizationPolicy,
    ProjectMembership,
    ProjectPermission,
    ProjectRole,
    permissions_for_role,
)
from .skills import (
    ExtractedSkillCard,
    SkillMatch,
    SkillRetrievalQuery,
    SuccessfulPatternExample,
    extract_reusable_skill_card,
    retrieve_relevant_skills,
)
from .vault import (
    EXPLORATION_DIRECTORIES,
    PROJECT_DIRECTORIES,
    VaultLayout,
    create_vault_layout,
)
from .versioning import (
    FileVersionSnapshot,
    RollbackResult,
    RollbackTargetType,
    StrategyKnowledgeRecord,
    VersionedFileStore,
    create_strategy_candidate,
    rollback_knowledge_entry,
    rollback_strategy_card,
    write_strategy_card_entry,
)

__all__ = [
    "AccessMode",
    "AgentRole",
    "EXPLORATION_DIRECTORIES",
    "ExtractedSkillCard",
    "FileVersionSnapshot",
    "KnowledgeEntry",
    "KnowledgeEntryType",
    "KnowledgeZone",
    "MarkdownKnowledgeStore",
    "PROJECT_DIRECTORIES",
    "PermissionManager",
    "ProjectAuthorizationPolicy",
    "ProjectMembership",
    "ProjectPermission",
    "ProjectRole",
    "RollbackResult",
    "RollbackTargetType",
    "SkillMatch",
    "SkillRetrievalQuery",
    "StrategyKnowledgeRecord",
    "SuccessfulPatternExample",
    "VersionedFileStore",
    "VaultLayout",
    "VersionSnapshot",
    "create_vault_layout",
    "create_strategy_candidate",
    "extract_wiki_links",
    "extract_reusable_skill_card",
    "permissions_for_role",
    "rollback_knowledge_entry",
    "rollback_strategy_card",
    "retrieve_relevant_skills",
    "write_strategy_card_entry",
]
