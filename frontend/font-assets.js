import { readFileSync } from 'node:fs';

// Keep segmented Chinese fonts as external, cacheable assets. Vite library
// mode would otherwise inline the entire font into the main stylesheet.
export function chineseFonts() {
  const root=new URL('./node_modules/@fontsource-variable/noto-sans-sc/',import.meta.url);
  return {
    name:'local-chinese-fonts',
    generateBundle() {
      const css=readFileSync(new URL('index.css',root),'utf8');
      const files=new Set([...css.matchAll(/url\(\.\/files\/([^)]*)\)/g)].map(match=>match[1]));
      for(const file of files)this.emitFile({type:'asset',fileName:`fonts/${file}`,source:readFileSync(new URL(`files/${file}`,root))});
      this.emitFile({type:'asset',fileName:'fonts.css',source:css.replaceAll('./files/','./fonts/')});
      this.emitFile({type:'asset',fileName:'fonts/LICENSE.txt',source:readFileSync(new URL('LICENSE',root))});
    },
  };
}
