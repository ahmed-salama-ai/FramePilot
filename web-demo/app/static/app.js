document.getElementById("up")?.addEventListener("submit", e => {
    e.preventDefault();
    const xhr = new XMLHttpRequest(), bar = document.getElementById("upbar");
    bar.hidden = false;
    xhr.upload.onprogress = ev => bar.value = 100 * ev.loaded / ev.total;
    xhr.onload = () => { 
        const r = JSON.parse(xhr.responseText); 
        location.href = `/jobs/${r.job_id}`; 
    };
    xhr.open("POST", "/api/projects"); 
    xhr.send(new FormData(e.target));
});
