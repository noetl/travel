import { clearSession } from "./gatewaySession";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  frontDesk,
  pollFrontDesk,
  PendingOperation,
  HoldIntent,
  money,
} from "./frontDesk";
vi.mock("./gatewaySession", () => ({
  getGatewayBaseUrl: () => "https://gateway.example.invalid",
  getStoredSession: () => ({ token: "test-session" }),
  clearSession: vi.fn(),
}));
const response = (body: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => body,
});
afterEach(() => vi.unstubAllGlobals());
describe("front desk boundary", () => {
  it("sends only request data to a fixed action route and polls a receipt", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        response({ execution_id: "9007199254740993", receipt: "signed" }),
      )
      .mockResolvedValueOnce(
        response({
          status: "COMPLETED",
          rows: [{ unit_id: "9007199254740993" }],
        }),
      );
    vi.stubGlobal("fetch", fetch);
    expect(await frontDesk("availability", { arrival: "2030-01-01" })).toEqual([
      { unit_id: "9007199254740993" },
    ]);
    expect(fetch.mock.calls[0][0]).toBe(
      "https://gateway.example.invalid/api/scoped/availability",
    );
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      request: { arrival: "2030-01-01" },
    });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
      receipt: "signed",
    });
  });
  it("preserves the receipt after a poll transport failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(Error("network")));
    await expect(pollFrontDesk("hold", "same-receipt")).rejects.toMatchObject({
      action: "hold",
      receipt: "same-receipt",
    });
  });
  it("does not report failed executions as successful empty results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ status: "FAILED", rows: [] })),
    );
    await expect(pollFrontDesk("hold", "signed")).rejects.toThrow("rejected");
  });
  it("denies unmapped accounts before polling", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({}, 403)));
    await expect(frontDesk("availability", {})).rejects.toThrow("not assigned");
  });
  it("retains idempotency keys across retries and changes them for a new intent", () => {
    const intent = new HoldIntent();
    const key = intent.for({ unit_id: "1", guests: 2 });
    expect(intent.for({ guests: 2, unit_id: "1" })).toBe(key);
    expect(intent.for({ unit_id: "2", guests: 2 })).not.toBe(key);
    const next = intent.for({ unit_id: "2", guests: 2 });
    intent.reset();
    expect(intent.for({ unit_id: "2", guests: 2 })).not.toBe(next);
  });
  it("formats exact bigint cents without floating-point loss", () => {
    expect(money("9007199254740993", "USD")).toBe("USD 90071992547409.93");
  });
});

it("clears expired sessions and rejects a write before any polling", async () => {
  const fetch = vi.fn().mockResolvedValue(response({}, 401));
  vi.stubGlobal("fetch", fetch);
  await expect(frontDesk("hold", {})).rejects.toThrow("session expired");
  expect(clearSession).toHaveBeenCalled();
  expect(fetch).toHaveBeenCalledTimes(1);
});
