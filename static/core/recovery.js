document.querySelectorAll('[data-countdown]').forEach(button=>{
  const end=Date.now()+Number(button.dataset.countdown)*1000;
  const timer=setInterval(()=>{const left=Math.max(0,Math.ceil((end-Date.now())/1000));
    if(left){button.querySelector('[data-countdown-value]').textContent=left;}
    else{clearInterval(timer);button.disabled=false;button.textContent='重新发送验证码';}},1000);
});
document.querySelectorAll('form.send-code,form.reset-password').forEach(form=>form.addEventListener('submit',()=>{
  const button=form.querySelector('button:not([type=button])');if(!button)return;button.disabled=true;
  button.textContent=form.classList.contains('send-code')?'正在发送…':'正在验证…';
}));
