import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite config for React frontend.
// - `base: '/app/'` ensures that built asset URLs work when the
//   app is served from FastAPI under the `/app` path in production.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  server: {
    port: 5173,
    proxy: {
      // Proxy API requests (not the SPA shell) to the FastAPI backend.
      '/app/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/app\/api/, '/api'),
      },
    },
  },
});
