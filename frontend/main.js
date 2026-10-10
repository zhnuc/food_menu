/* Konsta primitives render the existing page controller's escaped markup.
 * The controller owns state and actions; this module owns presentation only. */
import { h, render } from 'vue';
import { kApp, kProvider as kKonstaProvider, kNavbar, kButton, kCard, kChip,
  kSegmented, kSegmentedButton, kTabbar, kTabbarLink, kToolbarPane, kMenuList, kMenuListItem } from 'konsta/vue';
import './theme.css';

const provider=children=>h(kKonstaProvider,{theme:'material',dark:false,autoThemeDetection:false},{default:()=>children});
const propsOf=node=>Object.fromEntries([...node.attributes].map(attr=>[attr.name,attr.name==='disabled'?true:attr.value]));
const listOf=node=>[...node.childNodes].map(convert).filter(value=>value!==null);
function convert(node) {
  if(node.nodeType===3)return node.textContent;
  if(node.nodeType!==1)return null;
  const tag=node.tagName.toLowerCase(),props=propsOf(node),children=()=>listOf(node);
  if(node.classList.contains('select-options'))return h(kMenuList,{...props,component:'div',outline:false,inset:false,dividers:false,'data-konsta':'menu-list'},{default:children});
  if(node.classList.contains('select-entry')) {
    const choice=node.querySelector('button');
    return h(kMenuListItem,{component:'li',title:choice.querySelector('.select-option-label').textContent,linkComponent:'button',linkProps:{...propsOf(choice),type:'button'},contentClass:'select-option-content',innerClass:'select-option-inner','data-konsta':'menu-item'},
      {after:()=>h('span',{class:'select-option-check','aria-hidden':'true'},'✓')});
  }
  if(tag==='button') {
    const classes=node.classList;
    // Structural controls keep their own layout. Konsta's default button is
    // full-width; applying it to steppers and inline actions collapses the page.
    const primitive=['button-primary','button-secondary','circle-button','pick-button','text-link','household','food-tile'].some(name=>classes.contains(name)) || node.closest('.row-actions,.recipe-tools');
    if(!primitive)return h('button',{...props,type:props.type || (node.closest('form')?'submit':'button')},children());
    const tonal=classes.contains('button-secondary')||classes.contains('circle-button')||classes.contains('pick-button')||node.closest('.row-actions,.recipe-tools');
    const full=classes.contains('button-primary')||classes.contains('button-secondary')||classes.contains('food-tile')||node.closest('.row-actions');
    return h(kButton,{...props,component:'button',type:props.type || (node.closest('form')?'submit':'button'),inline:!full,rounded:true,clear:!tonal&&!classes.contains('button-primary'),tonal:!!tonal,large:classes.contains('button-primary'),disabled:node.hasAttribute('disabled'),'data-konsta':'button'},{default:children});
  }
  if(['recipe-card','prepare-row','profile-card','cooking-card','storage-note','dashboard-summary'].some(name=>node.classList.contains(name))) {
    return h(kCard,{...props,component:tag,contentWrap:false,raised:false,'data-konsta':'card'},{default:children});
  }
  if(tag==='span' && node.parentElement?.classList.contains('chips'))return h(kChip,{...props,component:'span',outline:false,'data-konsta':'chip'},{default:children});
  return h(tag,props,children());
}
function parse(html) {const template=document.createElement('template');template.innerHTML=html;return listOf(template.content);}
function draw(host,content) {
  // These roots contain native forms managed by the page controller. Unmount
  // the whole region so partial search/progress updates cannot leave stale VNodes.
  render(null,host);
  host.replaceChildren();
  render(provider(h('div',{class:'ui-region'},content)),host);
}
const shell=document.querySelector('.app-shell');
const host=document.createElement('div');host.id='konsta-root';shell.replaceWith(host);
const shellNodes=[...shell.childNodes].map(node=>{
  if(node.nodeType===1 && node.classList.contains('app-header')) {
    const brand=node.querySelector('.household');
    return h(kNavbar,{component:'header',class:'app-header',innerClass:'navbar-content',leftClass:'navbar-brand',rightClass:'navbar-roles',bgClass:'navbar-background',title:'',outline:false,'data-konsta':'navbar'},
      {left:()=>convert(brand),right:()=>h('div',{id:'role-control',class:'role-control'})});
  }
  return convert(node);
});
render(h(kApp,{theme:'material',dark:false,safeAreas:false,class:'kitchen-app','data-ui-theme':'material-green','data-konsta':'app'},
  {default:()=>h('div',{class:'app-shell'},shellNodes)}),host);

window.KonstaUI={
  region(id,html) {const target=document.getElementById(id);if(target)draw(target,parse(html));},
  roles(role) {
    const target=document.getElementById('role-control');
    render(provider(h(kSegmented,{strong:true,rounded:true,'data-konsta':'segmented'},
      {default:()=>[['chef','主厨'],['foodie','美食家']].map(([value,label])=>h(kSegmentedButton,
        {component:'button',type:'button',active:role===value,'aria-pressed':String(role===value),'data-action':'role','data-role':value},
        {default:()=>label}))})),target);
  },
  navigation(html) {
    const template=document.createElement('template');template.innerHTML=html;
    const buttons=[...template.content.querySelectorAll('button')];
    const links=buttons.map(button=>h(kTabbarLink,{component:'button',active:button.classList.contains('active'),
      linkProps:{...propsOf(button),type:'button'},label:button.querySelector('span').textContent,'data-konsta':'tabbar-link'},
      {icon:()=>{const graphic=convert(button.querySelector('img,svg')),count=button.querySelector('b');return [graphic,count?convert(count):null];}}));
    render(provider(h(kTabbar,{icons:true,labels:true,outline:false,class:'kitchen-tabbar','data-konsta':'tabbar'},
      {default:()=>h(kToolbarPane,{class:'kitchen-tabbar-pane'},{default:()=>links})})),document.getElementById('navigation'));
  },
  sheet(html) {
    // One overlay owns positioning and focus. Nesting Konsta's translating
    // Sheet inside a native dialog moves content above its visible bounds.
    draw(document.getElementById('sheet-body'),[h('div',{class:'sheet-content'},parse(html))]);
  },
};
window.KonstaUI.roles('chef');
// Native dialog retains focus trapping, Escape and accessible naming. Its
// contents and actions are Konsta components, with matching Material surfaces.
document.documentElement.classList.add('k-material');
document.addEventListener('click',event=>{
  const dialog=document.getElementById('sheet');if(event.target!==dialog || !dialog.open)return;
  const rect=dialog.getBoundingClientRect();
  if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();
});
