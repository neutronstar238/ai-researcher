/** 统一应用错误模型，保留 code/message/field_errors/trace_id（spec §9.4/§18.1） */
export interface FieldError {
  field: string;
  message: string;
}

export class AppError extends Error {
  code: string;
  status: number;
  traceId?: string;
  fieldErrors: FieldError[];

  constructor(
    message: string,
    code: string,
    status: number,
    traceId?: string,
    fieldErrors: FieldError[] = [],
  ) {
    super(message);
    this.name = "AppError";
    this.code = code;
    this.status = status;
    this.traceId = traceId;
    this.fieldErrors = fieldErrors;
  }
}
