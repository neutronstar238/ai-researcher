import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { appRoutes } from "../app/router";
import { ToastProvider } from "../components/ui/ToastRegion";

export function renderAppAt(path = "/", { strict = false }: { strict?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });

  const app: ReactNode = (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  );

  return {
    ...render(strict ? <StrictMode>{app}</StrictMode> : app),
    queryClient,
    router,
  };
}
