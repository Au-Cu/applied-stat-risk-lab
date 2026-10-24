import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {chromium} from 'playwright';
const root=process.argv[2],qa=path.join(root,'work/dynamic-applications-workbook-20261024');
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
  const page=await browser.newPage({viewport:{width:2100,height:1100},deviceScaleFactor:1.4});
  for(const name of ['ratios','ratio-details','quota-sources','quota-dates','raw','coverage']){
    await page.goto(pathToFileURL(path.join(qa,name+'.html')).href,{waitUntil:'load'});
    await page.evaluate(()=>document.fonts.ready);
    const size=await page.locator('table').boundingBox();
    await page.setViewportSize({width:Math.max(2100,Math.ceil(size.width+40)),height:Math.max(1100,Math.ceil(size.height+40))});
    await page.screenshot({path:path.join(qa,name+'.png'),clip:{x:0,y:0,width:Math.ceil(size.width+28),height:Math.ceil(size.height+28)}});
    console.log(JSON.stringify({view:name,width:Math.ceil(size.width),height:Math.ceil(size.height)}));
  }
}finally{await browser.close();}
