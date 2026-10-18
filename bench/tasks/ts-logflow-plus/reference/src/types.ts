export type Level = "debug" | "info" | "warn" | "error";

export interface Rec {
  ts: number;
  level: Level;
  service: string;
  msg: string;
  fields: Record<string, string>;
}

export class StageError extends Error {}

export type Args = Record<string, string>;
export type Transform = (records: Rec[], args: Args) => Rec[];
export type Report = (records: Rec[], args: Args) => string;

export interface Table {
  columns: string[];
  rows: string[][];
}
export type TableReport = (records: Rec[], args: Args) => Table;

export interface Plugin {
  name: string;
  transforms?: Record<string, Transform>;
  reports?: Record<string, Report>;
  tables?: Record<string, TableReport>;
}
