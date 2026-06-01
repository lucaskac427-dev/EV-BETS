import type { Config } from "drizzle-kit";

export default {
  schema: "./src/lib/schema.ts",
  dialect: "postgresql",
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "postgresql://kalshi:kalshi@localhost:5432/kalshi_ev",
  },
} satisfies Config;
