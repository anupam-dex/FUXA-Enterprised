import os

def patch():
    dist_file = os.path.join(os.path.dirname(__file__), '..', 'client', 'dist', 'main.48e6fe8b37377fdb.js')
    dist_file = os.path.abspath(dist_file)
    with open(dist_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. ngAfterViewInit failsafe timer in EditorComponent
    t1 = 'this.projectService.hasLazyViews()?this.projectService.reload(!0):this.loadHmi(!0)),this.subscriptionLoad=this.projectService.onLoadHmi.subscribe(n=>{this.loadHmi()},n=>{console.error("Error loadHMI")}),this.changeDetector.detectChanges()'
    r1 = 'this.projectService.hasLazyViews()?this.projectService.reload(!0):this.loadHmi(!0)),this.subscriptionLoad=this.projectService.onLoadHmi.subscribe(n=>{this.loadHmi()},n=>{console.error("Error loadHMI")}),setTimeout(()=>{this.isLoading&&((this.isLoading=!1),this.changeDetector.detectChanges())},4000),this.changeDetector.detectChanges()'
    assert content.count(t1) == 1, f"t1 count: {content.count(t1)}"

    # 2. loadHmi null-safety & finally block
    t2 = 'loadHmi(t=!1){if(this.gaugesManager.initGaugesMap(),this.currentView=null,this.hmi=this.projectService.getHmi(),this.hmi.views?.length<=0)this.hmi.views=[],this.addView(Qr.TR.MainViewName);else{let n=localStorage.getItem("@frango.webeditor.currentview");!n&&this.hmi.views.length&&(n=this.hmi.views[0].name);for(let i=0;i<this.hmi.views.length;i++)if(this.hmi.views[i].name===n&&this.hmi.views[i].type!==Gt.qi.maps){this.onSelectView(this.hmi.views[i]);break}this.currentView||this.onSelectView(this.hmi.views[0])}this.hmi.layout=gi.Aq.mergeDeep(new Gt.QQ,this.hmi.layout),this.hmi.layout.start||(this.hmi.layout.start=this.hmi.views[0]?.id),this.loadPanelState(),this.isLoading=!1}'
    r2 = 'loadHmi(t=!1){try{this.gaugesManager.initGaugesMap(),this.currentView=null,this.hmi=this.projectService.getHmi()||{views:[],layout:{}},!this.hmi.views&&(this.hmi.views=[]),this.hmi.views.length<=0?(this.hmi.views=[],this.addView(Qr.TR.MainViewName)):(()=>{let n=localStorage.getItem("@frango.webeditor.currentview");!n&&this.hmi.views.length&&(n=this.hmi.views[0]?.name);for(let i=0;i<this.hmi.views.length;i++)if(this.hmi.views[i]?.name===n&&this.hmi.views[i]?.type!==Gt.qi.maps){this.onSelectView(this.hmi.views[i]);break}this.currentView||(this.hmi.views.length>0&&this.onSelectView(this.hmi.views[0]))})(),this.hmi.layout=gi.Aq.mergeDeep(new Gt.QQ,this.hmi.layout||{}),this.hmi.layout.start||(this.hmi.layout.start=this.hmi.views[0]?.id)}catch(e){console.error("loadHmi error",e)}finally{try{this.loadPanelState()}catch(e){};this.isLoading=!1}}'
    assert content.count(t2) == 1, f"t2 count: {content.count(t2)}"

    # 3. loadView null-safety on svgcontent, profile, and items loop
    t3 = 'loadView(t){if(t)if(this.clearEditor(),this.isSvgEditMode(this.editorMode)){let n="",i=this.getView(t.name);i&&(n=i.svgcontent),n.length<=0&&(n=\'<svg id="\'+t.name+\'" width="\'+t.profile.width+\'" height="\'+t.profile.height+\'" xmlns="http://www.w3.org/2000/svg" xmlns:svg="http://www.w3.org/2000/svg"><filter id="blur-filter" x="-3" y="-3" width="200" height="200"><feGaussianBlur in="SourceGraphic" stdDeviation="3" /></filter><g><title>Layer 1</title></g></svg>\'),this.winRef.nativeWindow.svgEditor&&(this.winRef.nativeWindow.svgEditor.setDocProperty(t.name,t.profile.width,t.profile.height,t.profile.bkcolor),this.winRef.nativeWindow.svgEditor.setSvgString(n)),this.destroyRemovedGauges(),this.gaugesRef={},this.removedGaugeSettings={},i&&this.projectService.cleanView(i),setTimeout(()=>{for(let o in i.items){let s=this.getGaugeSettings(i.items[o]);this.checkGaugeAdded(s)}this.winRef.nativeWindow.svgEditor.refreshCanvas(),this.checkSvgElementsMap(!0),this.winRef.nativeWindow.svgEditor.resetUndoStack()},500)}else this.isCardsEditMode(this.editorMode)&&this.cardsview?(this.cardsview.view=t,this.cardsview.reload()):this.isMapsEditMode(this.editorMode)&&this.mapsView&&(this.mapsView.view=t,this.mapsView.reload())}'
    r3 = 'loadView(t){if(t)try{if(this.clearEditor(),this.isSvgEditMode(this.editorMode)){let n="",i=this.getView(t.name);i&&i.svgcontent&&(n=i.svgcontent);const _w=(t.profile&&t.profile.width)||1920,_h=(t.profile&&t.profile.height)||1080,_c=(t.profile&&t.profile.bkcolor)||"#12171f";(!n||n.length<=0)&&(n=\'<svg id="\'+(t.name||"view")+\'" width="\'+_w+\'" height="\'+_h+\'" xmlns="http://www.w3.org/2000/svg" xmlns:svg="http://www.w3.org/2000/svg"><filter id="blur-filter" x="-3" y="-3" width="200" height="200"><feGaussianBlur in="SourceGraphic" stdDeviation="3" /></filter><g><title>Layer 1</title></g></svg>\'),this.winRef.nativeWindow.svgEditor&&(this.winRef.nativeWindow.svgEditor.setDocProperty(t.name||"view",_w,_h,_c),this.winRef.nativeWindow.svgEditor.setSvgString(n)),this.destroyRemovedGauges(),this.gaugesRef={},this.removedGaugeSettings={},i&&this.projectService.cleanView(i),setTimeout(()=>{try{if(i&&i.items)for(let o in i.items){let s=this.getGaugeSettings(i.items[o]);this.checkGaugeAdded(s)}this.winRef.nativeWindow.svgEditor?.refreshCanvas?.(),this.checkSvgElementsMap(!0),this.winRef.nativeWindow.svgEditor?.resetUndoStack?.()}catch(e){console.warn(e)}},500)}else this.isCardsEditMode(this.editorMode)&&this.cardsview?(this.cardsview.view=t,this.cardsview.reload()):this.isMapsEditMode(this.editorMode)&&this.mapsView&&(this.mapsView.view=t,this.mapsView.reload())}catch(e){console.error("loadView error",e)}}'
    assert content.count(t3) == 1, f"t3 count: {content.count(t3)}"

    content = content.replace(t1, r1)
    content = content.replace(t2, r2)
    content = content.replace(t3, r3)

    with open(dist_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print("[✓] Successfully patched client/dist/main.48e6fe8b37377fdb.js")

if __name__ == '__main__':
    patch()
