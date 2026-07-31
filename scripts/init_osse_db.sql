CREATE TABLE IF NOT EXISTS orb_strength_score (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    run_id VARCHAR(100),
    orb_high FLOAT,
    orb_low FLOAT,
    orb_width FLOAT,
    orb_percent FLOAT,
    relative_volume FLOAT,
    atr FLOAT,
    adx FLOAT,
    ema_alignment FLOAT,
    vwap_distance FLOAT,
    candle_efficiency FLOAT,
    normalized_score FLOAT NOT NULL,
    decision VARCHAR(50) NOT NULL,
    trade_pnl FLOAT,
    mfe FLOAT,
    mae FLOAT,
    market_regime VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_orb_timestamp ON orb_strength_score(timestamp);
CREATE INDEX IF NOT EXISTS idx_orb_symbol ON orb_strength_score(symbol);
CREATE INDEX IF NOT EXISTS idx_orb_run_id ON orb_strength_score(run_id);

CREATE TABLE IF NOT EXISTS feature_distributions (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    feature_name VARCHAR(50) NOT NULL,
    mean_val FLOAT,
    std_val FLOAT,
    percentile_25 FLOAT,
    percentile_50 FLOAT,
    percentile_75 FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feat_dist_date ON feature_distributions(date);
CREATE INDEX IF NOT EXISTS idx_feat_dist_symbol ON feature_distributions(symbol);

-- Migration for existing tables
DO $$ 
BEGIN
    BEGIN
        ALTER TABLE orb_strength_score ADD COLUMN run_id VARCHAR(100);
    EXCEPTION
        WHEN duplicate_column THEN null;
    END;
    BEGIN
        ALTER TABLE orb_strength_score ADD COLUMN trade_pnl FLOAT;
    EXCEPTION
        WHEN duplicate_column THEN null;
    END;
    BEGIN
        ALTER TABLE orb_strength_score ADD COLUMN mfe FLOAT;
    EXCEPTION
        WHEN duplicate_column THEN null;
    END;
    BEGIN
        ALTER TABLE orb_strength_score ADD COLUMN mae FLOAT;
    EXCEPTION
        WHEN duplicate_column THEN null;
    END;
    BEGIN
        ALTER TABLE orb_strength_score ADD COLUMN market_regime VARCHAR(50);
    EXCEPTION
        WHEN duplicate_column THEN null;
    END;
END $$;

