import { QueryClient } from "@tanstack/react-query";

import { AppError } from "../api/errors";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        // 4xx 业务错误不自动重试；网络错误/5xx 只读最多退避重试 2 次（spec §9.4）
        if (error instanceof AppError && error.status >= 400 && error.status < 500) {
          return false;
        }
        return failureCount < 2;
      },
    },
  },
});
