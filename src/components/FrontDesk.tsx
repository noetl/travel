import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Container,
  Stack,
  TextField,
  Typography,
  Paper,
  Divider,
} from "@mui/material";
import { getStoredSession } from "../api/gatewaySession";
import { useMunoAuth } from "../auth/MunoAuthProvider";
import {
  frontDesk,
  HoldIntent,
  money,
  PendingOperation,
  pollFrontDesk,
  type Room,
  type Reservation,
} from "../api/frontDesk";

export function FrontDesk() {
  const auth = useMunoAuth();
  const [arrival, setArrival] = useState("");
  const [departure, setDeparture] = useState("");
  const [guests, setGuests] = useState(2);
  const [guest, setGuest] = useState("");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [lookup, setLookup] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<PendingOperation>();
  const intent = useRef(new HoldIntent());
  useEffect(() => {
    setRooms([]);
    setReservations([]);
    setGuest("");
    setLookup("");
    setPending(undefined);
    setBusy(false);
    setMessage("");
    setNotice("");
    intent.current.reset();
  }, [auth.user?.sub, auth.isGatewayLinked]);
  async function perform<T>(work: () => Promise<T>, done: (value: T) => void) {
    const session = getStoredSession()?.token;
    setBusy(true);
    setMessage("");
    setNotice("");
    try {
      const value = await work();
      if (getStoredSession()?.token !== session) return;
      done(value);
      setPending(undefined);
    } catch (e) {
      if (getStoredSession()?.token !== session) return;
      if (e instanceof PendingOperation) setPending(e);
      setMessage(e instanceof Error ? e.message : "Operation failed.");
    } finally {
      if (getStoredSession()?.token === session) setBusy(false);
    }
  }
  const remember = (rows: Reservation[]) => {
    if (!rows.length) {
      setNotice("No matching reservation was found.");
      return;
    }
    setReservations((current) => [
      ...rows,
      ...current.filter(
        (r) => !rows.some((n) => n.reservation_id === r.reservation_id),
      ),
    ]);
  };
  if (!auth.isGatewayLinked || !auth.isAuthenticated)
    return (
      <Container maxWidth="sm" sx={{ py: 8 }}>
        <Stack spacing={2}>
          <Typography variant="h4">Front desk</Typography>
          <Typography>
            Sign in with an assigned staff account to manage reservations.
          </Typography>
          {auth.gatewayError && (
            <Alert severity="error">{auth.gatewayError}</Alert>
          )}
          <Button
            variant="contained"
            disabled={
              !auth.isAuthConfigured || auth.isLoading || auth.isLinkingGateway
            }
            onClick={() => void auth.login()}
          >
            Sign in
          </Button>
          <Button onClick={auth.logout}>Sign out</Button>
        </Stack>
      </Container>
    );
  const validDates =
    /^\d{4}-\d{2}-\d{2}$/.test(arrival) &&
    /^\d{4}-\d{2}-\d{2}$/.test(departure) &&
    departure > arrival &&
    guests >= 1 &&
    guests <= 100;
  const hold = (room: Room) => {
    const input = {
      unit_id: room.unit_id,
      guest_id: guest,
      arrival,
      departure,
      guests,
    };
    void perform(
      () =>
        frontDesk<Reservation>("hold", {
          ...input,
          idempotency_key: intent.current.for(input),
        }),
      (rows) => {
        remember(rows);
        setRooms([]);
      },
    );
  };
  const transition = (r: Reservation, status: string) =>
    void perform(
      () =>
        frontDesk<Reservation>("transition", {
          reservation_id: r.reservation_id,
          status,
          expected_version: r.version,
        }),
      remember,
    );
  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Stack spacing={3}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
        >
          <Box>
            <Typography variant="h4" fontWeight={800}>
              Front desk
            </Typography>
            <Typography color="text.secondary">
              Availability and reservations
            </Typography>
          </Box>
        </Stack>
        {message && <Alert severity="error">{message}</Alert>}
        {notice && <Alert severity="info">{notice}</Alert>}
        {pending && (
          <Button
            disabled={busy}
            onClick={() =>
              void perform(
                () =>
                  pollFrontDesk<Reservation | Room>(
                    pending.action,
                    pending.receipt,
                  ),
                (rows) => {
                  if (pending.action === "availability")
                    setRooms(rows as Room[]);
                  else remember(rows as Reservation[]);
                },
              )
            }
          >
            Check pending operation
          </Button>
        )}
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Typography variant="h6">Find a room</Typography>
            <Button
              disabled={busy || !!pending}
              onClick={() => {
                intent.current.reset();
                setRooms([]);
                setGuest("");
                setNotice("New booking started.");
              }}
            >
              Start a new booking
            </Button>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                disabled={busy || !!pending}
                label="Arrival"
                type="date"
                value={arrival}
                InputLabelProps={{ shrink: true }}
                onChange={(e) => {
                  setArrival(e.target.value);
                  setRooms([]);
                }}
              />
              <TextField
                label="Departure"
                type="date"
                value={departure}
                InputLabelProps={{ shrink: true }}
                onChange={(e) => {
                  setDeparture(e.target.value);
                  setRooms([]);
                }}
              />
              <TextField
                label="Guests"
                type="number"
                value={guests}
                inputProps={{ min: 1, max: 100 }}
                onChange={(e) => {
                  setGuests(Number(e.target.value));
                  setRooms([]);
                }}
              />
              <Button
                variant="contained"
                disabled={busy || !!pending || !validDates}
                onClick={() =>
                  void perform(
                    () =>
                      frontDesk<Room>("availability", {
                        arrival,
                        departure,
                        guests,
                      }),
                    (rows) => {
                      setRooms(rows);
                      if (!rows.length)
                        setNotice("No rooms are available for these dates.");
                    },
                  )
                }
              >
                Find availability
              </Button>
            </Stack>
            <TextField
              label="Existing guest account ID"
              value={guest}
              onChange={(e) => setGuest(e.target.value)}
              helperText="Use the guest account assigned during enrollment."
            />
            {rooms.map((room) => (
              <Stack
                key={room.unit_id}
                direction="row"
                justifyContent="space-between"
                alignItems="center"
              >
                <Box>
                  <Typography fontWeight={700}>
                    Room {room.unit_code}
                  </Typography>
                  <Typography>
                    {room.nights} nights ·{" "}
                    {money(room.total_cents, room.currency_code)} · sleeps{" "}
                    {room.capacity}
                  </Typography>
                </Box>
                <Button
                  disabled={busy || !!pending || !/^\d+$/.test(guest)}
                  onClick={() => hold(room)}
                >
                  Hold for 15 minutes
                </Button>
              </Stack>
            ))}
          </Stack>
        </Paper>
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Typography variant="h6">Reservations</Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                label="Reservation ID"
                value={lookup}
                onChange={(e) => setLookup(e.target.value)}
              />
              <Button
                disabled={busy || !!pending || !/^\d+$/.test(lookup)}
                onClick={() =>
                  void perform(
                    () =>
                      frontDesk<Reservation>("reservation", {
                        reservation_id: lookup,
                      }),
                    remember,
                  )
                }
              >
                Find reservation
              </Button>
              <Button
                disabled={busy || !!pending}
                onClick={() =>
                  void perform(
                    () => frontDesk<Reservation>("reservations", {}),
                    (rows) => {
                      setReservations(rows);
                      if (!rows.length) setNotice("No reservations found.");
                    },
                  )
                }
              >
                Load recent reservations
              </Button>
              <Button
                disabled={busy || !!pending}
                onClick={() =>
                  void perform(
                    () => frontDesk<Reservation>("release_expired", {}),
                    (rows) => {
                      remember(rows);
                      setNotice(`${rows.length} expired holds released.`);
                    },
                  )
                }
              >
                Release expired holds
              </Button>
            </Stack>
            <Typography variant="body2" color="text.secondary">
              Shows up to 100 recent reservations. Confirmation does not collect
              payment.
            </Typography>
            {reservations.map((r) => (
              <Box key={r.reservation_id}>
                <Divider sx={{ mb: 2 }} />
                <Typography fontWeight={700}>
                  Reservation {r.reservation_id} · {r.status.replace(/_/g, " ")}
                </Typography>
                <Typography>
                  Room {r.unit_id} · Guest {r.guest_id} · {r.arrival} →{" "}
                  {r.departure}
                </Typography>
                <Typography>{money(r.total_cents, r.currency_code)}</Typography>
                {r.status === "held" && (
                  <Typography variant="body2">
                    Hold expires {new Date(r.expires_at).toLocaleString()}
                  </Typography>
                )}
                <Stack direction="row" spacing={1}>
                  {r.status === "held" && (
                    <Button
                      disabled={busy || !!pending}
                      onClick={() => transition(r, "confirmed")}
                    >
                      Confirm reservation
                    </Button>
                  )}
                  {["held", "confirmed"].includes(r.status) && (
                    <Button
                      color="warning"
                      disabled={busy || !!pending}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Cancel reservation ${r.reservation_id}?`,
                          )
                        )
                          transition(r, "cancelled");
                      }}
                    >
                      Cancel reservation
                    </Button>
                  )}
                  {r.status === "confirmed" && (
                    <Button
                      disabled={busy || !!pending}
                      onClick={() => transition(r, "checked_in")}
                    >
                      Check in
                    </Button>
                  )}
                  {r.status === "checked_in" && (
                    <Button
                      disabled={busy || !!pending}
                      onClick={() => transition(r, "checked_out")}
                    >
                      Check out
                    </Button>
                  )}
                </Stack>
              </Box>
            ))}
          </Stack>
        </Paper>
      </Stack>
    </Container>
  );
}
