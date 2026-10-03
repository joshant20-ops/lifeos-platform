(async()=>{
  const bundle='/local/house-status-dev/lifeos-house-status-dev.js?dev='+Date.now();
  try{
    await import(bundle);
  }catch(error){
    console.error('House Status development panel failed to load',error);
    throw error;
  }
})();
