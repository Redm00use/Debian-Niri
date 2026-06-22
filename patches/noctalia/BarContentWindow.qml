import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Modules.Bar
import qs.Services.UI

PanelWindow {
  id: barWindow

  color: "transparent"
  visible: contentLoaded && BarService.effectivelyVisible

  Component.onCompleted: {
    Logger.d("BarContentWindow", "Bar content window created for screen:", barWindow.screen?.name);
  }

  WlrLayershell.namespace: "noctalia-bar-content-" + (barWindow.screen?.name || "unknown")
  WlrLayershell.layer: WlrLayer.Top
  WlrLayershell.exclusionMode: ExclusionMode.Ignore

  readonly property string barPosition: Settings.getBarPositionForScreen(barWindow.screen?.name)
  readonly property bool barIsVertical: barPosition === "left" || barPosition === "right"
  readonly property bool isFramed: Settings.data.bar.barType === "framed"
  readonly property real frameThickness: Settings.data.bar.frameThickness ?? 12
  readonly property bool barFloating: Settings.data.bar.floating || false
  readonly property real barMarginH: Math.ceil(barFloating ? Settings.data.bar.marginHorizontal : 0)
  readonly property real barMarginV: Math.ceil(barFloating ? Settings.data.bar.marginVertical : 0)
  readonly property real barHeight: Style.getBarHeightForScreen(barWindow.screen?.name)

  readonly property bool autoHide: Settings.getBarDisplayModeForScreen(barWindow.screen?.name) === "auto_hide"
  readonly property int hideDelay: Settings.data.bar.autoHideDelay || 500
  readonly property int showDelay: Settings.data.bar.autoShowDelay || 100
  property bool isHidden: autoHide
  property bool barHovered: false
  readonly property bool panelOpen: PanelService.openedPanel !== null

  Timer {
    id: hideTimer
    interval: barWindow.hideDelay
    onTriggered: {
      if (barWindow.autoHide && !barWindow.barHovered && !barWindow.panelOpen && !BarService.popupOpen) {
        BarService.setScreenHidden(barWindow.screen?.name, true);
      }
    }
  }

  Timer {
    id: showTimer
    interval: barWindow.showDelay
    onTriggered: {
      if (barWindow.autoHide && BarService.isBarHovered(barWindow.screen?.name)) {
        BarService.setScreenHidden(barWindow.screen?.name, false);
      }
    }
  }

  Connections {
    target: BarService
    function onBarAutoHideStateChanged(screenName, hidden) {
      if (screenName === barWindow.screen?.name) {
        barWindow.isHidden = hidden;
      }
    }
    function onBarHoverStateChanged(screenName, hovered) {
      if (screenName === barWindow.screen?.name && barWindow.autoHide) {
        if (hovered) {
          hideTimer.stop();
          if (!barWindow.isHidden) {
            showTimer.stop();
          } else {
            showTimer.restart();
          }
        } else if (!barWindow.barHovered && !barWindow.panelOpen) {
          showTimer.stop();
          hideTimer.restart();
        }
      }
    }
  }

  onPanelOpenChanged: {
    if (panelOpen && autoHide) {
      hideTimer.stop();
      BarService.setScreenHidden(barWindow.screen?.name, false);
    } else if (!panelOpen && autoHide && !barHovered) {
      hideTimer.restart();
    }
  }

  Connections {
    target: BarService
    function onPopupOpenChanged() {
      if (!BarService.popupOpen && barWindow.autoHide && !barWindow.barHovered && !barWindow.panelOpen) {
        hideTimer.restart();
      }
    }
  }

  onAutoHideChanged: {
    if (!autoHide) {
      hideTimer.stop();
      showTimer.stop();
      barWindow.isHidden = false;
    }
  }

  anchors {
    top: barPosition === "top" || barIsVertical
    bottom: barPosition === "bottom" || barIsVertical
    left: barPosition === "left" || !barIsVertical
    right: barPosition === "right" || !barIsVertical
  }

  property bool contentLoaded: !isHidden

  Timer {
    id: unloadTimer
    interval: Style.animationFast + 50
    onTriggered: {
      if (barWindow.isHidden && !showTimer.running) {
        barWindow.barHovered = false;
        barWindow.contentLoaded = false;
      }
    }
  }

  onIsHiddenChanged: {
    if (isHidden) {
      unloadTimer.restart();
    } else {
      unloadTimer.stop();
      deferredUnloadTimer.stop();
      contentLoaded = true;
    }
  }

  Timer {
    id: deferredUnloadTimer
    interval: 1000
    onTriggered: {
      if (!BarService.effectivelyVisible) {
        barWindow.barHovered = false;
        barWindow.contentLoaded = false;
      }
    }
  }

  Connections {
    target: BarService
    function onEffectivelyVisibleChanged() {
      if (!BarService.effectivelyVisible) {
        deferredUnloadTimer.restart();
      } else {
        deferredUnloadTimer.stop();
        if (!barWindow.isHidden) {
          barWindow.contentLoaded = true;
        }
      }
    }
  }

  margins {
    top: (barPosition === "top") ? barMarginV : (isFramed ? frameThickness : barMarginV)
    bottom: (barPosition === "bottom") ? barMarginV : (isFramed ? frameThickness : barMarginV)
    left: (barPosition === "left") ? barMarginH : (isFramed ? frameThickness : barMarginH)
    right: (barPosition === "right") ? barMarginH : (isFramed ? frameThickness : barMarginH)
  }

  implicitWidth: barIsVertical ? barHeight : Math.min(barWindow.screen.width, 560)
  implicitHeight: barIsVertical ? barWindow.screen.height : barHeight

  Loader {
    id: barLoader
    anchors.fill: parent
    active: barWindow.contentLoaded

    sourceComponent: Item {
      anchors.fill: parent
      opacity: barWindow.isHidden ? 0 : 1

      Behavior on opacity {
        enabled: barWindow.autoHide
        NumberAnimation {
          duration: Style.animationFast
          easing.type: Easing.OutQuad
        }
      }

      Bar {
        id: barContent
        anchors.fill: parent
        screen: barWindow.screen

        HoverHandler {
          id: hoverHandler
          onHoveredChanged: {
            if (hovered) {
              barWindow.barHovered = true;
              BarService.setScreenHovered(barWindow.screen?.name, true);
              if (barWindow.autoHide) {
                hideTimer.stop();
                showTimer.restart();
              }
            } else {
              if (barWindow.isHidden)
                return;
              barWindow.barHovered = false;
              BarService.setScreenHovered(barWindow.screen?.name, false);
              if (barWindow.autoHide && !barWindow.panelOpen) {
                showTimer.stop();
                hideTimer.restart();
              }
            }
          }
        }
      }
    }
  }
}
