import type { ArtifactRecord } from "../api/types";

export type ArtifactWorkspace = "literature" | "experiments" | "assets" | "writing";

const WORKSPACE_TOKENS: Record<Exclude<ArtifactWorkspace, "assets" | "writing">, readonly string[]> = {
  literature: ["literature", "source"],
  experiments: ["experiment", "pilot", "metrics"],
};

function containsWorkspaceToken(artifact: ArtifactRecord, tokens: readonly string[]): boolean {
  const category = artifact.category.toLowerCase();
  const path = artifact.relative_path.toLowerCase();
  return tokens.some((token) => category.includes(token) || path.includes(token));
}

function isWritingArtifact(artifact: ArtifactRecord): boolean {
  return containsWorkspaceToken(artifact, ["plan", "review"]) || /\.(pdf|tex|md|markdown)$/i.test(artifact.relative_path);
}

export function filterArtifacts(
  artifacts: ArtifactRecord[],
  workspace: ArtifactWorkspace,
): ArtifactRecord[] {
  if (workspace === "assets") return [...artifacts];
  if (workspace === "writing") return artifacts.filter(isWritingArtifact);
  return artifacts.filter((artifact) => containsWorkspaceToken(artifact, WORKSPACE_TOKENS[workspace]));
}
