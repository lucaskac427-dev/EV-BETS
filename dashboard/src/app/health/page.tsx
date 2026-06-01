import { HealthCard } from "@/components/HealthCard";

export default function HealthPage() {
  return (
    <main className="max-w-2xl mx-auto px-6 py-8 space-y-6">
      <a href="/" className="text-xs text-zinc-500 hover:text-zinc-300">
        ← back
      </a>
      <h1 className="text-lg font-semibold">Scanner health</h1>
      <HealthCard />
    </main>
  );
}
