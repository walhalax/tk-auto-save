// LiveChat slider video

function loadScript(callback, callbackError) {
    var script = document.createElement("script");
    script.type = "text/javascript";
    script.id = "SCSpotScript";

    try {
        if (script.readyState) {  //IE
            script.onreadystatechange = function () {
                if (script.readyState === "loaded" || script.readyState === "complete") {
                    script.onreadystatechange = null;
                    callback();
                }
            };
        } else {  
            //other browser onload
            script.onload = function () {
                callback();
            };
        }

        script.src = 'https://creative.tklivechat.com/widgets/Spot/lib.js';
        document.getElementsByTagName("head")[0].appendChild(script);
    } catch (e) {
        if (null !== callbackError) callbackError(e);
    }
}

loadScript(function () {

  var container = document.createElement("div");
  document.body.appendChild(container);

  var spot = new StripchatSpot({
    targetDomain: 'tklivechat.com',
    autoplay: "all",
    userId: "fbe991993b1d5c2eb1733620d878551006570012587b6ec7fe908ac7c206baff",
    campaignId: 'videoslider',
    quality: '480p',
    tag: 'girls/japanese',
    //showModal: "signup",
    hideButton: "1",
    autoclose: 0,
    closeButtonDelay: 0
  });
  function waitMounted() {
    return new Promise(function(resolve) {
      setTimeout(function() {
        resolve(container.firstElementChild ? true : waitMounted());
      }, 50);
    });
  }
  spot.mount(container).then(waitMounted).then(function() {
    Object.assign(container.firstElementChild.style, {   maxWidth: '20%', maxHeight: 'calc(20%)' });
  });
});