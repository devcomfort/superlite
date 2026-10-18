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
