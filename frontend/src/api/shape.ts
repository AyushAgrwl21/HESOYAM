export class ShapeError extends Error {
  constructor(detail: string) {
    super(
      `The API response did not match the documented shape (${detail}). No figures were inferred.`,
    );
    this.name = "ShapeError";
  }
}

export function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ShapeError(label);
  }
  return value as Record<string, unknown>;
}

function read(record: Record<string, unknown>, name: string): unknown {
  if (!Object.hasOwn(record, name)) {
    throw new ShapeError(name);
  }
  return record[name];
}

export function requireString(record: Record<string, unknown>, name: string): string {
  const value = read(record, name);
  if (typeof value !== "string" || value.length === 0) {
    throw new ShapeError(name);
  }
  return value;
}

export function requireNullableString(
  record: Record<string, unknown>,
  name: string,
): string | null {
  const value = read(record, name);
  if (value === null) {
    return null;
  }
  if (typeof value !== "string" || value.length === 0) {
    throw new ShapeError(name);
  }
  return value;
}

export function requireBoolean(record: Record<string, unknown>, name: string): boolean {
  const value = read(record, name);
  if (typeof value !== "boolean") {
    throw new ShapeError(name);
  }
  return value;
}

export function requireInt(record: Record<string, unknown>, name: string, minimum = 0): number {
  const value = read(record, name);
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) {
    throw new ShapeError(name);
  }
  return value;
}

export function requireNullableInt(
  record: Record<string, unknown>,
  name: string,
): number | null {
  const value = read(record, name);
  if (value === null) {
    return null;
  }
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new ShapeError(name);
  }
  return value;
}

export function requireNullableFinite(
  record: Record<string, unknown>,
  name: string,
): number | null {
  const value = read(record, name);
  if (value === null) {
    return null;
  }
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ShapeError(name);
  }
  return value;
}

export function requireLiteral<T extends string>(
  record: Record<string, unknown>,
  name: string,
  expected: readonly T[],
): T {
  const value = read(record, name);
  if (typeof value !== "string" || !expected.includes(value as T)) {
    throw new ShapeError(name);
  }
  return value as T;
}

export function requireStringList(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.length === 0)) {
    throw new ShapeError(label);
  }
  return value as string[];
}
