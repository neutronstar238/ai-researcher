import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";

import { Providers } from "./providers";
import { router } from "./router";
import { useAuthStore } from "../stores/authStore";

function AuthBootstrap() {
  const restore = useAuthStore((state) => state.restore);
  useEffect(() => {
    void restore();
  }, [restore]);
  return <RouterProvider router={router} />;
}

export default function App() {
  return (
    <Providers>
      <AuthBootstrap />
    </Providers>
  );
}
