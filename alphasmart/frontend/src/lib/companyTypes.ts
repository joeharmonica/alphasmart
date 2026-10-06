export interface UniverseRow {
  symbol: string;
  name: string;
  sector: string | null;
  industry: string | null;
  price: number | null;
  chg1d: number | null;
  chg1m: number | null;
  chgYtd: number | null;
  chg1y: number | null;
  marketCap: number | null;
  trailingPE: number | null;
  forwardPE: number | null;
  priceToSales: number | null;
  evToEbitda: number | null;
  profitMargin: number | null;
  roe: number | null;
  revenueGrowth: number | null;
  dividendYield: number | null;
  recommendation: string | null;
  spark: (number | null)[];
  error: string | null;
}

export interface Universe {
  asOf: string;
  rows: UniverseRow[];
}

export type Profile = Record<string, string | number | null> & { symbol: string };

export interface Bar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Prices {
  symbol: string;
  bars: Bar[];
  benchmark: { symbol: string; bars: { t: string; c: number }[] };
}

export interface Statement {
  periods: string[];
  rows: { label: string; values: (number | null)[] }[];
}

export interface RatioPoint {
  period: string;
  grossMargin: number | null;
  operatingMargin: number | null;
  netMargin: number | null;
  fcfMargin: number | null;
  roe: number | null;
  roa: number | null;
  debtToEquity: number | null;
  revenueGrowth: number | null;
  epsGrowth: number | null;
  priceAtPeriodEnd: number | null;
  pe: number | null;
  ps: number | null;
  pfcf: number | null;
}

export interface Financials {
  symbol: string;
  annual: { income: Statement; balance: Statement; cashflow: Statement };
  quarterly: { income: Statement; balance: Statement; cashflow: Statement };
  ratioHistory: RatioPoint[];
  /** currency the statements are reported in (e.g. DKK for NVO) */
  currency: string;
  tradingCurrency: string;
}

export interface EarningsEvent {
  date: string;
  epsEstimate: number | null;
  epsActual: number | null;
  surprisePct: number | null;
}

export type Rec = Record<string, string | number | null>;

export interface Earnings {
  symbol: string;
  history: EarningsEvent[];
  upcoming: EarningsEvent | null;
  epsEstimates: Rec[];
  revenueEstimates: Rec[];
  epsTrend: Rec[];
  recommendations: Rec[];
}

export interface NewsItem {
  title: string;
  link: string;
  summary: string;
  published: string | null;
  relevant: boolean;
}

export interface News {
  symbol: string;
  items: NewsItem[];
}
