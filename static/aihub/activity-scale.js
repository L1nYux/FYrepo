/* A fixed share of the weekly base allowance, never relative to the busiest day. */
(function(root){
  const percent=(cost,limit)=>limit!==null&&Number(limit)>0?Number(cost)/Number(limit)*100:null;
  const level=(cost,limit,calls=0)=>Number(cost)<=0?(calls?1:0):percent(cost,limit)===null?1:Math.min(6,1+Math.floor((percent(cost,limit)+1e-9)/5));
  const api={percent,level};if(typeof module!=='undefined')module.exports=api;else root.workbenchActivityScale=api;
})(typeof window==='undefined'?globalThis:window);
