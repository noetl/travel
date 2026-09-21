-- DESIGN DRAFT ONLY: not executed against PostgreSQL in this environment.
-- Tables are proposed support for the playbook command boundary.
-- Stored functions, grants, RLS policies, migrations/rollback and rate engine are
-- intentionally pending. This file alone does NOT implement booking safety.
BEGIN;
CREATE SCHEMA hospitality;
CREATE TABLE hospitality.tenant (
  tenant_id uuid PRIMARY KEY,
  name text NOT NULL
);
CREATE TABLE hospitality.property (
  tenant_id uuid NOT NULL REFERENCES hospitality.tenant,
  property_id uuid NOT NULL,
  name text NOT NULL,
  timezone text NOT NULL,
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  PRIMARY KEY (tenant_id, property_id)
);
CREATE TABLE hospitality.membership (
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  subject_id text NOT NULL,
  role text NOT NULL CHECK (role IN ('staff','manager','worker')),
  PRIMARY KEY (tenant_id,property_id,subject_id,role),
  FOREIGN KEY (tenant_id,property_id) REFERENCES hospitality.property
);
CREATE TABLE hospitality.room (
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  room_id uuid NOT NULL,
  name text NOT NULL,
  max_guests integer NOT NULL CHECK (max_guests>0),
  PRIMARY KEY (tenant_id,property_id,room_id),
  FOREIGN KEY (tenant_id,property_id) REFERENCES hospitality.property
);
CREATE TABLE hospitality.quote (
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  quote_id uuid NOT NULL,
  room_id uuid NOT NULL,
  arrival date NOT NULL,
  departure date NOT NULL CHECK (departure>arrival),
  guests integer NOT NULL CHECK (guests>0),
  amount_minor bigint NOT NULL CHECK (amount_minor>=0),
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  pricing_snapshot jsonb NOT NULL,
  policy_version text NOT NULL,
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id,property_id,quote_id),
  UNIQUE (tenant_id,property_id,quote_id,room_id),
  FOREIGN KEY (tenant_id,property_id,room_id) REFERENCES hospitality.room
);
CREATE TABLE hospitality.reservation (
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  quote_id uuid NOT NULL,
  room_id uuid NOT NULL,
  arrival date NOT NULL,
  departure date NOT NULL CHECK (departure>arrival),
  state text NOT NULL CHECK (state IN ('held','confirmed','expired','canceled','needs_refund')),
  expires_at timestamptz NOT NULL,
  amount_minor bigint NOT NULL CHECK (amount_minor>=0),
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  PRIMARY KEY (tenant_id,property_id,reservation_id),
  UNIQUE (tenant_id,property_id,quote_id),
  UNIQUE (tenant_id,property_id,reservation_id,room_id),
  FOREIGN KEY (tenant_id,property_id,quote_id,room_id) REFERENCES hospitality.quote (tenant_id,property_id,quote_id,room_id)
);
CREATE TABLE hospitality.room_night (
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  room_id uuid NOT NULL,
  night date NOT NULL,
  reservation_id uuid,
  blocked boolean NOT NULL DEFAULT false,
  PRIMARY KEY (tenant_id,property_id,room_id,night),
  CHECK (NOT blocked OR reservation_id IS NULL),
  FOREIGN KEY (tenant_id,property_id,room_id) REFERENCES hospitality.room,
  FOREIGN KEY (tenant_id,property_id,reservation_id,room_id) REFERENCES hospitality.reservation (tenant_id,property_id,reservation_id,room_id)
);
CREATE TABLE hospitality.payment_attempt (
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  provider text NOT NULL,
  merchant_account_id text NOT NULL,
  provider_idempotency_key text NOT NULL,
  amount_minor bigint NOT NULL CHECK (amount_minor>=0),
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  state text NOT NULL CHECK (state IN ('created','pending','unknown','declined','captured')),
  PRIMARY KEY (tenant_id,property_id,attempt_id),
  UNIQUE (provider,merchant_account_id,provider_idempotency_key),
  UNIQUE (tenant_id,property_id,attempt_id,reservation_id),
  FOREIGN KEY (tenant_id,property_id,reservation_id) REFERENCES hospitality.reservation
);
CREATE TABLE hospitality.payment (
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  payment_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  provider text NOT NULL,
  merchant_account_id text NOT NULL,
  provider_transaction_id text NOT NULL,
  amount_minor bigint NOT NULL CHECK (amount_minor>=0),
  currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  status text NOT NULL CHECK (status IN ('captured','voided','refunded')),
  PRIMARY KEY (tenant_id,property_id,payment_id),
  UNIQUE (provider,merchant_account_id,provider_transaction_id),
  FOREIGN KEY (tenant_id,property_id,attempt_id,reservation_id) REFERENCES hospitality.payment_attempt (tenant_id,property_id,attempt_id,reservation_id)
);
CREATE TABLE hospitality.command_request (
  tenant_id uuid NOT NULL,
  principal_id text NOT NULL,
  operation text NOT NULL,
  idempotency_key text NOT NULL,
  canonical_payload jsonb NOT NULL,
  response jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (tenant_id,principal_id,operation,idempotency_key)
);
CREATE TABLE hospitality.webhook_inbox (
  provider text NOT NULL,
  merchant_account_id text NOT NULL,
  provider_event_id text NOT NULL,
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  verified_payload jsonb NOT NULL,
  processed_at timestamptz,
  PRIMARY KEY (provider,merchant_account_id,provider_event_id),
  FOREIGN KEY (tenant_id,property_id) REFERENCES hospitality.property
);
CREATE TABLE hospitality.business_outbox (
  tenant_id uuid NOT NULL,
  property_id uuid NOT NULL,
  event_id uuid NOT NULL,
  reservation_id uuid NOT NULL,
  event_type text NOT NULL,
  aggregate_version bigint NOT NULL CHECK (aggregate_version>0),
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  published_at timestamptz,
  lease_until timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id,property_id,event_id),
  UNIQUE (tenant_id,property_id,reservation_id,aggregate_version),
  FOREIGN KEY (tenant_id,property_id,reservation_id) REFERENCES hospitality.reservation
);
CREATE INDEX pending_outbox ON hospitality.business_outbox(created_at) WHERE published_at IS NULL;
CREATE INDEX expiring_holds ON hospitality.reservation(expires_at) WHERE state='held';
-- Do not grant application access until command functions and RLS are implemented.
REVOKE ALL ON SCHEMA hospitality FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA hospitality FROM PUBLIC;
COMMIT;
