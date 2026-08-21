import { apiClient, ApiError, request } from "./client";

test("lists runs from the response envelope", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          runs: [{ run_id: "run-12345678", direction: "问题", status: "queued" }],
        }),
        { status: 200 },
      ),
    ),
  );

  await expect(apiClient.listRuns()).resolves.toHaveLength(1);
});

test("preserves the backend JSON error status, message, and code", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: "service_error", message: "run cannot resume" }),
        { status: 409 },
      ),
    ),
  );

  await expect(apiClient.resumeRun("run-12345678")).rejects.toMatchObject({
    status: 409,
    message: "run cannot resume",
    code: "service_error",
  } satisfies Partial<ApiError>);
});

test("falls back to the HTTP status text for a non-JSON error response", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response("gateway unavailable", { status: 502, statusText: "Bad Gateway" }),
    ),
  );

  await expect(apiClient.health()).rejects.toMatchObject({
    status: 502,
    message: "Bad Gateway",
    code: "request_failed",
  } satisfies Partial<ApiError>);
});

test("encodes a run ID before placing it in a request path", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ run_id: "run/a b" }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  await apiClient.getRun("run/a b");

  expect(fetchMock).toHaveBeenCalledWith("/api/runs/run%2Fa%20b", expect.any(Object));
});

test("sends JSON POST headers and body when creating a run", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ run_id: "run-12345678" }), { status: 201 }));
  vi.stubGlobal("fetch", fetchMock);

  await apiClient.createRun({ direction: "测试研究", dry_run: true });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/runs",
    expect.objectContaining({
      method: "POST",
      headers: expect.any(Headers),
      body: JSON.stringify({ direction: "测试研究", dry_run: true }),
    }),
  );
  const [, requestInit] = fetchMock.mock.calls[0]!;
  expect(Array.from(new Headers((requestInit as RequestInit).headers).entries())).toEqual([
    ["content-type", "application/json"],
  ]);
});

test("uses a caller content type in place of the JSON default without duplication", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  await request("/api/health", { headers: { "content-type": "text/plain" } });

  const [, requestInit] = fetchMock.mock.calls[0]!;
  const headers = new Headers((requestInit as RequestInit).headers);
  expect(headers.get("Content-Type")).toBe("text/plain");
  expect(Array.from(headers.entries())).toEqual([["content-type", "text/plain"]]);
});

test("gets the exact skill candidates endpoint and unwraps its candidates envelope", async () => {
  const candidates = [{
    candidate_skill_id: "candidate-wire",
    parent_skill: null,
    candidate_status: "shadow_evaluation",
    relative_path: "exploration/skills/candidates/candidate-wire.md",
    promotion_authorized: false,
    promotion_boundary: "shadow evidence only",
  }];
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ candidates }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(apiClient.skillCandidates()).resolves.toEqual(candidates);
  expect(fetchMock).toHaveBeenCalledWith("/api/skills/candidates", expect.not.objectContaining({ method: "POST" }));
});

test("uses an encoded run ID for evolution GET and POST, sends no invented body, and preserves the receipt", async () => {
  const status = {
    run_id: "run/evolution wire",
    execution_enabled: true,
    mode: "frozen_service_available",
    selected_skills: { run_id: "run/evolution wire", source_artifact: null, selection: null, skill_content_is_scientific_evidence: false },
    skill_candidates: [],
    run_evolution_receipt: null,
    promotion_authorized: false,
    boundary: "persisted state only",
  };
  const receipt = {
    schema_version: "autoresearch-api-skill-evolution-receipt-v1",
    run_id: "run/evolution wire",
    status: "shadow_validated",
    result: { receipt_id: "receipt-wire", nested: { preserved: true } },
    promotion_authorized: false,
    created_at: "2026-08-20T08:00:00Z",
  };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(status), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(receipt), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(apiClient.evolution("run/evolution wire")).resolves.toEqual(status);
  await expect(apiClient.startEvolution("run/evolution wire")).resolves.toEqual(receipt);
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/runs/run%2Fevolution%20wire/evolution");
  expect(fetchMock.mock.calls[0]?.[1]).not.toEqual(expect.objectContaining({ method: "POST" }));
  expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/runs/run%2Fevolution%20wire/evolution");
  expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ method: "POST" }));
  expect((fetchMock.mock.calls[1]?.[1] as RequestInit).body).toBeUndefined();
});

test("preserves all seven health capability booleans without coercion", async () => {
  const health = {
    status: "ok",
    service: "autoresearch-local-api",
    deployment_scope: "local_single_user",
    authentication_enabled: true,
    formal_experiment_enabled: false,
    result_paper_enabled: true,
    self_evolution_execution_enabled: false,
    self_evolution_service_configured: true,
    automatic_skill_activation_enabled: false,
    batch_execution_configured: true,
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(health), { status: 200 })));

  await expect(apiClient.health()).resolves.toEqual(health);
});

test("preserves artifact server URLs and relative paths from the run detail response", async () => {
  const artifact = {
    relative_path: "artifacts/literature/source paper.pdf",
    category: "literature",
    bytes: 321,
    sha256: "abcdef0123456789",
    media_type: "application/pdf",
    url: "/api/runs/run%2Fdetail/artifacts/artifacts%2Fliterature%2Fsource%20paper.pdf",
  };
  const run = { run_id: "run/detail", artifacts: [artifact] };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(run), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  const response = await apiClient.getRun("run/detail");
  expect(response.artifacts?.[0]).toEqual(artifact);
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/runs/run%2Fdetail");
});
