// Fallback visual QA of the saved workbook's XML-derived views on Windows.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {chromium} from 'playwright';
const root=process.argv[2];
const qa=path.join(root,'work/quota-deadline-workbook-20261023');
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try {
  const page=await browser.newPage({viewport:{width:2500,height:1050},deviceScaleFactor:1});
  for(const name of ['quota-main','quota-dates','quota-scope','quota-calendar','quota-gaps']) {
    await page.goto(pathToFileURL(path.join(qa,name+'.html')).href,{waitUntil:'load'});
    await page.evaluate(()=>document.fonts.ready);
    const size=await page.locator('table').boundingBox();
    await page.screenshot({path:path.join(qa,name+'.png'),clip:{x:0,y:0,width:Math.ceil(size.width+28),height:Math.ceil(size.height+28)}});
    console.log(JSON.stringify({view:name,width:Math.ceil(size.width),height:Math.ceil(size.height)}));
  }
}finally{await browser.close();}
