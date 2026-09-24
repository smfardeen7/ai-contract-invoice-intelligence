const status = document.querySelector('#status');
const queue = document.querySelector('#queue');
const node = (tag, text, cls) => {const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;};
async function refresh(){
  try {
    const response=await fetch('/api/invoices');
    if(!response.ok)throw new Error('Unable to load invoices');
    const docs=await response.json();queue.replaceChildren();
    if(!docs.length)queue.append(node('p','No invoices yet. Submit the sample to inspect a result.'));
    for(const doc of docs){
      const card=node('article','','invoice');
      card.append(node('span',doc.status.replaceAll('_',' ').toUpperCase(),'badge '+(doc.status==='needs_review'?'review':'')));
      card.append(node('h3',`${doc.invoice.invoice_id} · ${doc.invoice.vendor}`));
      card.append(node('div',`${doc.invoice.currency} ${doc.invoice.total} · Due ${doc.invoice.due}`,'meta'));
      const issues=node('ul','');for(const issue of doc.issues)issues.append(node('li',issue.message));card.append(issues);queue.append(card);
    }
  }catch(error){status.textContent=error.message;}
}
document.querySelector('#ingest').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;status.textContent='Processing…';
  try{
    const response=await fetch('/api/invoices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:document.querySelector('#text').value})});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Request failed');
    status.textContent=result.duplicate?'Already ingested: returning the existing result.':`Stored: ${result.status.replaceAll('_',' ')}.`;await refresh();
  }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector('#refresh').addEventListener('click',refresh);refresh();
