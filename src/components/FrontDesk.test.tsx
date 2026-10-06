import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FrontDesk } from "./FrontDesk";
const state = vi.hoisted(() => ({ linked: false, authenticated: false }));
vi.mock("../auth/MunoAuthProvider", () => ({
  useMunoAuth: () => ({
    isGatewayLinked: state.linked,
    isAuthenticated: state.authenticated,
    isAuthConfigured: true,
    allowGuest: true,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));
describe("front desk authentication gate", () => {
  beforeEach(() => {
    state.linked = false;
    state.authenticated = false;
  });
  it("guest mode never exposes reservation actions", () => {
    const html = renderToStaticMarkup(<FrontDesk />);
    expect(html).toContain("assigned staff account");
    expect(html).not.toContain("Find availability");
    expect(html).not.toContain("Load recent reservations");
  });
  it("requires gateway linkage even after identity-provider sign-in", () => {
    state.authenticated = true;
    expect(renderToStaticMarkup(<FrontDesk />)).not.toContain(
      "Find availability",
    );
  });
  it("renders staff actions and unpaid-confirmation language after linkage", () => {
    state.authenticated = true;
    state.linked = true;
    const html = renderToStaticMarkup(<FrontDesk />);
    expect(html).toContain("Find availability");
    expect(html).toContain("Confirmation does not collect payment");
    expect(html).toContain("Start a new booking");
  });
});
