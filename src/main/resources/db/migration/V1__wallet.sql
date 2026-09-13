CREATE TABLE app_users (
  id UUID PRIMARY KEY,
  token_hash VARCHAR(64) NOT NULL UNIQUE,
  opening_balance_paise BIGINT NOT NULL CHECK (opening_balance_paise BETWEEN 0 AND 1000000000),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE wallets (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL UNIQUE REFERENCES app_users(id),
  balance_paise BIGINT NOT NULL CHECK (balance_paise >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE transfers (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES app_users(id),
  idempotency_key VARCHAR(128) NOT NULL,
  from_wallet UUID NOT NULL REFERENCES wallets(id),
  to_wallet UUID NOT NULL REFERENCES wallets(id),
  amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
  status VARCHAR(16) NOT NULL CHECK (status IN ('PENDING','COMPLETED','DECLINED')),
  reason VARCHAR(40),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, idempotency_key),
  CHECK (from_wallet <> to_wallet)
);
CREATE INDEX transfers_from_idx ON transfers(from_wallet);
CREATE INDEX transfers_to_idx ON transfers(to_wallet);
