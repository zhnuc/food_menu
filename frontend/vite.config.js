import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import vue from '@vitejs/plugin-vue';
import { chineseFonts } from './font-assets.js';

export default defineConfig({
  define: { 'process.env.NODE_ENV': '"production"', __VUE_OPTIONS_API__: true, __VUE_PROD_DEVTOOLS__: false, __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: false },
  plugins: [vue(), tailwindcss(), chineseFonts()],
  build: {
    outDir: '../web/ui',
    emptyOutDir: true,
    lib: { entry: 'main.js', name: 'KitchenUI', formats: ['iife'], fileName: () => 'konsta-app.js', cssFileName: 'konsta-app' },
  },
});
