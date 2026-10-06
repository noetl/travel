import {
  getGatewayBaseUrl,
  getStoredSession,
  clearSession,
} from "./gatewaySession";
export type Action =
  | "availability"
  | "hold"
  | "reservation"
  | "reservations"
  | "transition"
  | "release_expired";
export interface Room {
  unit_id: string;
  unit_code: string;
  capacity: number;
  currency_code: string;
  nightly_rate: string;
  total_cents: string;
  nights: number;
}
export interface Reservation {
  reservation_id: string;
  unit_id: string;
  guest_id: string;
  arrival: string;
  departure: string;
  guests: number;
  status: string;
  version: number;
  currency_code: string;
  total_cents: string;
  expires_at: string;
}
class WorkflowRejected extends Error {}
export class PendingOperation extends Error {
  constructor(
    public action: Action,
    public receipt: string,
  ) {
    super(
      "Still processing. Check the same operation again before starting another.",
    );
  }
}
async function request(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  const token = getStoredSession()?.token;
  if (!token) throw Error("Sign in to use the front desk.");
  const response = await fetch(`${getGatewayBaseUrl()}/api/scoped/${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal: signal ?? AbortSignal.timeout(25000),
  });
  if (response.status === 401) {
    clearSession();
    throw Error("Your session expired. Sign in again.");
  }
  if (response.status === 403)
    throw Error("Your account is not assigned to this front desk.");
  if (!response.ok)
    throw Error(
      "The operation could not be completed. Check the reservation before retrying.",
    );
  return response.json() as Promise<Record<string, unknown>>;
}
export async function pollFrontDesk<T>(
  action: Action,
  receipt: string,
  signal?: AbortSignal,
): Promise<T[]> {
  for (let i = 0; i < 40; i++) {
    let value: Record<string, unknown>;
    try {
      value = await request(`${action}/result`, { receipt }, signal);
    } catch {
      throw new PendingOperation(action, receipt);
    }
    if (value.status === "COMPLETED") {
      if (!Array.isArray(value.rows))
        throw Error("The service returned an incomplete result.");
      return value.rows as T[];
    }
    if (value.status === "FAILED" || value.status === "CANCELLED")
      throw new WorkflowRejected(
        "The operation was rejected. Refresh availability or the reservation before trying again.",
      );
    if (value.status !== "RUNNING")
      throw Error("The service returned an unknown operation state.");
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new PendingOperation(action, receipt);
}
export async function frontDesk<T>(
  action: Action,
  input: Record<string, unknown>,
): Promise<T[]> {
  const value = await request(action, { request: input });
  if (typeof value.receipt !== "string")
    throw Error("No operation receipt was returned.");
  return pollFrontDesk<T>(action, value.receipt);
}
export function money(cents: string, currency: string): string {
  const value = BigInt(cents);
  return `${currency} ${value / 100n}.${(value % 100n).toString().padStart(2, "0")}`;
}
export class HoldIntent {
  private fingerprint = "";
  private key = "";
  for(input: Record<string, unknown>): string {
    const value = JSON.stringify(
      Object.entries(input).sort(([a], [b]) => a.localeCompare(b)),
    );
    if (value !== this.fingerprint) {
      this.fingerprint = value;
      this.key = crypto.randomUUID();
    }
    return this.key;
  }
  reset() {
    this.fingerprint = "";
    this.key = "";
  }
}
