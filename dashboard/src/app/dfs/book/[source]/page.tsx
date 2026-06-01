import { notFound } from "next/navigation";

import { DfsBoard, DFS_PLATFORMS } from "@/components/DfsBoard";

export default async function DfsPlatformPage({
  params,
}: {
  params: Promise<{ source: string }>;
}) {
  const { source } = await params;
  if (!DFS_PLATFORMS[source]) notFound();
  return <DfsBoard source={source} />;
}
