import type { ArtifactRecord } from "../api/types";
import { artifactFixtures } from "../../test/fixtures";
import { filterArtifacts } from "./artifacts";

const writingArtifacts: ArtifactRecord[] = [
  {
    relative_path: "deliveries/results.pdf",
    category: "unknown",
    bytes: 1,
    sha256: "d".repeat(64),
    media_type: "application/pdf",
    url: "/pdf",
  },
  {
    relative_path: "manuscript/draft.TEX",
    category: "unknown",
    bytes: 1,
    sha256: "e".repeat(64),
    media_type: "application/x-tex",
    url: "/tex",
  },
  {
    relative_path: "notes/discussion.markdown",
    category: "unknown",
    bytes: 1,
    sha256: "f".repeat(64),
    media_type: "text/markdown",
    url: "/markdown",
  },
  {
    relative_path: "data/raw.csv",
    category: "dataset",
    bytes: 1,
    sha256: "0".repeat(64),
    media_type: "text/csv",
    url: "/csv",
  },
];

function artifact(relativePath: string, category: string): ArtifactRecord {
  return {
    relative_path: relativePath,
    category,
    bytes: 1,
    sha256: "1".repeat(64),
    media_type: "application/json",
    url: `/${relativePath}`,
  };
}

test("filters literature and experiment workspaces by category or path", () => {
  const artifacts = artifactFixtures();

  expect(filterArtifacts(artifacts, "literature").map((artifact) => artifact.relative_path)).toEqual([
    "literature/broad/source.json",
  ]);
  expect(filterArtifacts(artifacts, "experiments").map((artifact) => artifact.relative_path)).toEqual([
    "pilot/metrics.json",
  ]);
});

test("filters literature and experiments with category-only signals", () => {
  const artifacts = [
    artifact("unclassified/a.json", "literature"),
    artifact("unclassified/b.json", "experiment"),
  ];

  expect(filterArtifacts(artifacts, "literature").map((item) => item.relative_path)).toEqual([
    "unclassified/a.json",
  ]);
  expect(filterArtifacts(artifacts, "experiments").map((item) => item.relative_path)).toEqual([
    "unclassified/b.json",
  ]);
});

test("filters literature and experiments with path-only signals", () => {
  const artifacts = [
    artifact("sources/bibliography.json", "unknown"),
    artifact("real-pilot/observations.json", "unknown"),
  ];

  expect(filterArtifacts(artifacts, "literature").map((item) => item.relative_path)).toEqual([
    "sources/bibliography.json",
  ]);
  expect(filterArtifacts(artifacts, "experiments").map((item) => item.relative_path)).toEqual([
    "real-pilot/observations.json",
  ]);
});

test("matches mixed-case category and path signals for literature and experiments", () => {
  const artifacts = [
    artifact("unclassified/a.json", "LiTeRaTuRe"),
    artifact("SoUrCeS/b.json", "unknown"),
    artifact("unclassified/c.json", "MeTrIcS"),
    artifact("ReAl-PiLoT/d.json", "unknown"),
  ];

  expect(filterArtifacts(artifacts, "literature").map((item) => item.relative_path)).toEqual([
    "unclassified/a.json",
    "SoUrCeS/b.json",
  ]);
  expect(filterArtifacts(artifacts, "experiments").map((item) => item.relative_path)).toEqual([
    "unclassified/c.json",
    "ReAl-PiLoT/d.json",
  ]);
});

test("recognizes PDF, TeX, and Markdown files in the writing workspace", () => {
  expect(filterArtifacts(writingArtifacts, "writing").map((artifact) => artifact.relative_path)).toEqual([
    "deliveries/results.pdf",
    "manuscript/draft.TEX",
    "notes/discussion.markdown",
  ]);
});

test("keeps unknown categories in all assets without mutating the caller array", () => {
  const artifacts = [...artifactFixtures(), ...writingArtifacts];
  const originalPaths = artifacts.map((artifact) => artifact.relative_path);

  const result = filterArtifacts(artifacts, "assets");

  expect(result).toHaveLength(7);
  expect(result.map((artifact) => artifact.relative_path)).toEqual(originalPaths);
  expect(artifacts.map((artifact) => artifact.relative_path)).toEqual(originalPaths);
  expect(result).not.toBe(artifacts);
});
