import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { Input } from "@/sjsu/components/ui/input";
import { Badge } from "@/sjsu/components/ui/badge";
import { Card, CardContent } from "@/sjsu/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/sjsu/components/ui/table";
import { SortableHead } from "@/sjsu/components/ui/sortable-head";
import { useTableSort } from "@/sjsu/lib/use-table-sort";
import { ChevronDown, ChevronRight, TriangleAlert } from "lucide-react";
import { ApplicationReviewDialog } from "./application-review-dialog";
import { DIVERGENCE_THRESHOLD, type TableRow as AppRow } from "./review-data";

type SortField = "student" | "scholarship" | "score";

// shape returned by GET /applications (apps/api/main.py)
type ApiRow = {
  application_key: string;
  student: string;
  scholarship: string;
  year: string | null;
  major: string;
  level: string;
  gpa: number | null;
  aiPercent: number | null;
  humanPercent: number | null;
  delta: number | null;
  lowCount: number;
  needsHuman: boolean;
  status: "scored" | "pending";
};

function toRow(r: ApiRow): AppRow {
  const ai = r.aiPercent ?? 0;
  return {
    id: r.application_key, student: r.student, scholarship: r.scholarship,
    year: r.year ?? "", major: r.major, level: r.level, gpa: r.gpa, status: r.status,
    aiComposite: ai, aiCompositeMax: 100, aiPercent: ai,
    humanPercent: r.humanPercent, delta: r.delta, needsHuman: r.needsHuman, lowCount: r.lowCount,
  };
}

export function ApplicationsTable() {
  const [search, setSearch] = useState("");
  const [showAgreed, setShowAgreed] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const { sortBy, sortDir, setSort } = useTableSort<SortField>();
  const sortProps = { sortBy, sortDir, onSort: setSort } as const;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["applications"],
    queryFn: () => api<{ applications: ApiRow[] }>("/applications"),
  });

  const rows = useMemo(() => (data?.applications ?? []).map(toRow), [data]);

  const { needsHuman, agreed } = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = query
      ? rows.filter((r) => `${r.student} ${r.scholarship} ${r.major}`.toLowerCase().includes(query))
      : rows;

    const dir = sortDir === "asc" ? 1 : -1;
    const sorted = [...filtered].sort((a, b) => {
      if (!sortBy) return (Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0)) || (b.aiPercent - a.aiPercent);
      if (sortBy === "score") return (a.aiPercent - b.aiPercent) * dir;
      return String(a[sortBy]).localeCompare(String(b[sortBy])) * dir;
    });

    return {
      needsHuman: sorted.filter((r) => r.needsHuman),
      agreed: sorted.filter((r) => !r.needsHuman),
    };
  }, [rows, search, sortBy, sortDir]);

  const visible = showAgreed ? [...needsHuman, ...agreed] : needsHuman;
  const total = needsHuman.length + agreed.length;
  const withHuman = [...needsHuman, ...agreed].filter((r) => r.delta != null);
  const agreeRate = withHuman.length === 0
    ? null
    : Math.round((withHuman.filter((r) => Math.abs(r.delta as number) < DIVERGENCE_THRESHOLD).length / withHuman.length) * 100);

  return (
    <>
      <div className="mb-4 flex items-center gap-2">
        <h1 className="font-mondwest text-3xl">Applications</h1>
        <Badge variant="secondary">SJSU General - phase 1</Badge>
        {isLoading && <Badge variant="secondary">loading</Badge>}
        {isError && <Badge variant="warning">api error</Badge>}
      </div>

      <div className="mb-6 grid max-w-2xl grid-cols-3 gap-3">
        <StatCard value={total} label="applications" />
        <StatCard value={agreeRate == null ? "-" : `${agreeRate}%`} label="AI + human agree" />
        <StatCard value={needsHuman.length} label="need a human" />
      </div>

      <Input
        placeholder="Search student, major, or scholarship"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        className="mb-4 max-w-sm"
      />

      {isError ? (
        <EmptyMsg>
          Could not reach the API{error instanceof Error ? `: ${error.message}` : ""}. Is it running on{" "}
          <code>:3005</code> (<code>pnpm dev:api</code>)?
        </EmptyMsg>
      ) : isLoading ? (
        <EmptyMsg>Loading applications...</EmptyMsg>
      ) : total === 0 ? (
        <EmptyMsg>No applications yet - upload an xlsx to the parse-trigger bucket to populate the pipeline.</EmptyMsg>
      ) : (
        <Table>
          <colgroup>
            <col className="w-28" /><col className="w-36" /><col className="w-64" /><col className="w-40" />
          </colgroup>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <SortableHead field="student" {...sortProps}>Student</SortableHead>
              <SortableHead field="scholarship" {...sortProps}>Scholarship</SortableHead>
              <TableHead>Major</TableHead>
              <SortableHead field="score" {...sortProps}>AI score</SortableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <PileHeader>
              <TriangleAlert className="size-3.5 text-warning" />
              needs a human ({needsHuman.length})
            </PileHeader>
            {needsHuman.map((row, i) => (
              <ApplicationRow key={row.id} row={row} onClick={() => setSelected(i)} />
            ))}

            <TableRow className="cursor-pointer hover:bg-muted/50" onClick={() => setShowAgreed((v) => !v)}>
              <TableCell colSpan={4} className="py-2 text-xs font-medium text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  {showAgreed ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                  rest ({agreed.length})
                </span>
              </TableCell>
            </TableRow>
            {showAgreed &&
              agreed.map((row, i) => (
                <ApplicationRow key={row.id} row={row} onClick={() => setSelected(needsHuman.length + i)} />
              ))}
          </TableBody>
        </Table>
      )}

      <ApplicationReviewDialog
        app={selected != null ? visible[selected] ?? null : null}
        index={selected ?? 0}
        total={visible.length}
        onOpenChange={(open) => !open && setSelected(null)}
        onPrev={() => setSelected((i) => (i == null ? i : (i - 1 + visible.length) % visible.length))}
        onNext={() => setSelected((i) => (i == null ? i : (i + 1) % visible.length))}
      />
    </>
  );
}

function StatCard({ value, label }: { value: number | string; label: string }) {
  return (
    <Card size="sm" className="gap-1">
      <CardContent>
        <div className="font-mondwest text-3xl leading-none">{value}</div>
        <div className="mt-1 text-xs text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  );
}

function EmptyMsg({ children }: { children: React.ReactNode }) {
  return (
    <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">{children}</CardContent></Card>
  );
}

function PileHeader({ children }: { children: React.ReactNode }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={4} className="py-2 text-xs font-medium text-muted-foreground">
        <span className="flex items-center gap-1.5">{children}</span>
      </TableCell>
    </TableRow>
  );
}

function ApplicationRow({ row, onClick }: { row: AppRow; onClick: () => void }) {
  return (
    <TableRow className="cursor-pointer" onClick={onClick}>
      <TableCell className="font-medium">{row.student}</TableCell>
      <TableCell>{row.scholarship}</TableCell>
      <TableCell className="truncate text-muted-foreground">{row.major}</TableCell>
      <TableCell>
        {row.status !== "scored" ? (
          <span className="text-xs text-muted-foreground">pending</span>
        ) : (
          <div className="flex items-center gap-2" title={`${row.aiComposite} / ${row.aiCompositeMax}`}>
            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${row.aiPercent}%` }} />
            </div>
            <span className="tabular-nums text-xs text-muted-foreground">{row.aiPercent}%</span>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}
