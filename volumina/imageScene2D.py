#!/usr/bin/env python
# -*- coding: utf-8 -*-

#    Copyright 2010, 2011 C Sommer, C Straehle, U Koethe, FA Hamprecht. All rights reserved.
#    
#    Redistribution and use in source and binary forms, with or without modification, are
#    permitted provided that the following conditions are met:
#    
#       1. Redistributions of source code must retain the above copyright notice, this list of
#          conditions and the following disclaimer.
#    
#       2. Redistributions in binary form must reproduce the above copyright notice, this list
#          of conditions and the following disclaimer in the documentation and/or other materials
#          provided with the distribution.
#    
#    THIS SOFTWARE IS PROVIDED BY THE ABOVE COPYRIGHT HOLDERS ``AS IS'' AND ANY EXPRESS OR IMPLIED
#    WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
#    FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE ABOVE COPYRIGHT HOLDERS OR
#    CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#    CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#    SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
#    ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
#    NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
#    ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#    
#    The views and conclusions contained in the software and documentation are those of the
#    authors and should not be interpreted as representing official policies, either expressed
#    or implied, of their employers.

import numpy

import volumina
from volumina.colorama import Fore, Back, Style

from functools import partial
from PyQt4.QtCore import QRect, QRectF, QMutex, QPointF, Qt, QSizeF
from PyQt4.QtGui import QGraphicsScene, QImage, QTransform, QPen, QColor, QBrush, \
                        QFont, QPainter, QGraphicsItem

from imageSceneRendering import ImageSceneRenderThread

from volumina.tiling import *

#*******************************************************************************
# I m a g e S c e n e 2 D                                                      *
#*******************************************************************************
class DirtyIndicator(QGraphicsItem):
    """
    Indicates the computation progress of each tile. Each tile can be composed
    of multiple layers and is dirty as long as any of these layer tiles are
    not yet computed/up to date. The number of layer tiles still missing is
    indicated by a 'pie' chart.
    """
    def __init__(self, tiling):
        QGraphicsItem.__init__(self, parent=None)
        self._tiling = tiling
        self._indicate = numpy.zeros(len(tiling))

    def boundingRect(self):
        return self._tiling.boundingRectF()
    
    def paint(self, painter, option, widget):
        dirtyColor = QColor(255,0,0)
        doneColor  = QColor(0,255 ,0)
        painter.setOpacity(0.5)
        painter.save()
        painter.setBrush(QBrush(dirtyColor, Qt.SolidPattern))
        painter.setPen(dirtyColor)

        for i,p in enumerate(self._tiling.rectF):
            if self._indicate[i] == 1.0:
                continue
            w,h = p.width(), p.height()
            r = min(w,h)
            rectangle = QRectF(p.center()-QPointF(r/4,r/4), QSizeF(r/2, r/2));
            startAngle = 0 * 16
            spanAngle  = min(360*16, int((1.0-self._indicate[i])*360.0) * 16)
            painter.drawPie(rectangle, startAngle, spanAngle)

        painter.restore()

    def setTileProgress(self, tileId, progress):
        self._indicate[tileId] = progress
        self.update()

#*******************************************************************************
# I m a g e S c e n e 2 D                                                      *
#*******************************************************************************

class ImageScene2D(QGraphicsScene):
    """
    The 2D scene description of a tiled image generated by evaluating
    an overlay stack, together with a 2D cursor.
    """
    
    @property
    def stackedImageSources(self):
        return self._stackedImageSources
    
    @stackedImageSources.setter
    def stackedImageSources(self, s):
        self._stackedImageSources = s
        s.layerDirty.connect(self._onLayerDirty)
        self._initializePatches()
        s.stackChanged.connect(partial(self._invalidateRect, QRect()))
        s.aboutToResize.connect(self._onAboutToResize)
        self._numLayers = len(s)
        self._initializePatches()

    def _onAboutToResize(self, newSize):
        self._renderThread.stop()
        self._numLayers = newSize
        self._initializePatches()
        self._renderThread.start()

    @property
    def showDebugPatches(self):
        return self._showDebugPatches
    @showDebugPatches.setter
    def showDebugPatches(self, show):
        self._showDebugPatches = show
        self._invalidateRect()

    @property
    def sceneShape(self):
        """
        The shape of the scene in QGraphicsView's coordinate system.
        """
        return (self.sceneRect().width(), self.sceneRect().height())
    @sceneShape.setter
    def sceneShape(self, sceneShape):
        """
        Set the size of the scene in QGraphicsView's coordinate system.
        sceneShape -- (widthX, widthY),
        where the origin of the coordinate system is in the upper left corner
        of the screen and 'x' points right and 'y' points down
        """   
            
        assert len(sceneShape) == 2
        self.setSceneRect(0,0, *sceneShape)
        
        #The scene shape is in Qt's QGraphicsScene coordinate system,
        #that is the origin is in the top left of the screen, and the
        #'x' axis points to the right and the 'y' axis down.
        
        #The coordinate system of the data handles things differently.
        #The x axis points down and the y axis points to the right.
        
        r = self.scene2data.mapRect(QRect(0,0,sceneShape[0], sceneShape[1]))
        sliceShape = (r.width(), r.height())
        
        del self._renderThread
        if self._dirtyIndicator:
            self.removeItem(self._dirtyIndicator)
        del self._dirtyIndicator

        self._tiling = Tiling(sliceShape, self.data2scene)
        self._dirtyIndicator = DirtyIndicator(self._tiling)
        self.addItem(self._dirtyIndicator)
            
        self._renderThread = ImageSceneRenderThread(self.stackedImageSources, parent=self)
        self._renderThread.start()
        
        self._renderThread.patchAvailable.connect(self._schedulePatchRedraw)
        
        self._initializePatches()

    def __init__( self ):
        QGraphicsScene.__init__(self)
        self._updatableTiles = []

        # tiled rendering of patches
        self._imageLayers    = None
        self._compositeLayer = None
        self._brushingLayer  = None
        # indicates the dirtyness of each tile
        self._dirtyIndicator = None

        self._renderThread = None
        self._stackedImageSources = None
        self._numLayers = 0 #current number of 'layers'
        self._showDebugPatches = False
    
        self.data2scene = QTransform(0,1,1,0,0,0) 
        self.scene2data = self.data2scene.transposed()
        
        self._slicingPositionSettled = True
    
        def cleanup():
            self._renderThread.stop()
        self.destroyed.connect(cleanup)
    
    def _initializePatches(self):
        if not self._renderThread:
            return
              
        self._renderThread.stop()
        
        self._imageLayers= [TiledImageLayer(self._tiling) for i in range(self._numLayers)]
        self._compositeLayer = TiledImageLayer(self._tiling)
        self._brushingLayer  = TiledImageLayer(self._tiling)

        self._renderThread._imageLayers    = self._imageLayers
        self._renderThread._compositeLayer = self._compositeLayer
        self._renderThread._brushingLayer  = self._brushingLayer
        self._renderThread._tiling         = self._tiling

        self._renderThread.start()
   
    def drawLine(self, fromPoint, toPoint, pen):
        tileId = self._tiling.containsF(toPoint)
        if tileId is None:
            return
       
        p = self._brushingLayer[tileId] 
        p.lock()
        painter = QPainter(p.image)
        painter.setPen(pen)
        
        tL = self._tiling._imageRectF[tileId].topLeft()
        painter.drawLine(fromPoint-tL, toPoint-tL)
        painter.end()
        p.dataVer += 1
        p.unlock()
        self._schedulePatchRedraw(tileId)

    def _onLayerDirty(self, layerNr, rect):
        for tileId in self._tiling.intersected(rect):
            p = self._imageLayers[layerNr][tileId]
            p.dataVer += 1
        
        self._invalidateRect(rect)
            
    def _invalidateRect(self, rect = QRect()):
        if not rect.isValid():
            #everything is invalidated
            #we cancel all requests
            self._renderThread.cancelAll()
            self._updatableTiles = []
            
            for p in self._brushingLayer:
                p.lock()
                p.image.fill(0)
                p.imgVer = p.dataVer
                p.unlock()
            
            for layer in self._imageLayers:
                for p in layer:
                    p.lock()
                    p.dataVer += 1
                    p.unlock() 
        
        for tileId in self._tiling.intersected(rect):
            self._dirtyIndicator.setTileProgress(tileId, 1.0)

            p = self._compositeLayer[tileId]
            p.dataVer += 1
            self._schedulePatchRedraw(tileId)
                
    def _schedulePatchRedraw(self, tileId) :
        r = self._tiling.rectF[tileId]
        #in QGraphicsScene::update, which is triggered by the
        #invalidate call below, the code
        #
        #view->d_func()->updateRectF(view->viewportTransform().mapRect(rect))
        #
        #seems to introduce rounding errors to the mapped rectangle.
        #
        #While we invalidate only one patch's rect, the rounding errors
        #enlarge the rect slightly, so that when update() is triggered
        #the neighbouring patches are also affected.
        #
        #To compensate, adjust the rectangle slightly (less than one pixel,
        #so it should not matter) 
        self.invalidate(r, QGraphicsScene.BackgroundLayer)

    def drawForeground(self, painter, rect):
        patches = self._tiling.intersectedF(rect)

        for tileId in patches:
            p = self._brushingLayer[tileId]
            if p.dataVer == p.imgVer:
                continue

            p.paint(painter) #access to the underlying image patch is serialized
    
    def indicateSlicingPositionSettled(self, settled):
        self._dirtyIndicator.setVisible(settled)
        self._slicingPositionSettled = settled
    
    def drawBackground(self, painter, rect):
        #Find all patches that intersect the given 'rect'.

        patches = self._tiling.intersectedF(rect)

        for tileId in patches: 
            for layerNr, tiledLayer in enumerate(self._imageLayers):
                p = tiledLayer[tileId]
        
                p.lock()
                if p.imgVer != p.dataVer and p.reqVer != p.dataVer:
                    #
                    if volumina.verboseRequests:
                        volumina.printLock.acquire()
                        print Fore.RED + "ImageScene2D '%s' asks for layer=%d, patch %d = (x=%d, y=%d, w=%d, h=%d)" \
                              % (self.objectName(), layerNr, p.tileId, p.patchRectF.x(), p.patchRectF.y(), \
                                 Np.patchRectF.width(), p.patchRectF.height()) + Fore.RESET
                        volumina.printLock.release()
                    #
                    self._renderThread.requestPatch((layerNr, tileId))
                    p.reqVer = p.dataVer
                p.unlock()
        
        #draw composite patches
        tiles = [self._compositeLayer[i] for i in patches]
        for tileId, p in zip(patches, tiles):
            p.paint(painter)
        
        #calculate progress information for 'pie' progress indicators on top
        #of each tile
        for tileId in patches:
            numDirtyLayers = 0
            for layer in self._imageLayers:
                _p = layer[tileId]
                _p.lock()
                if _p.imgVer != _p.dataVer:
                    numDirtyLayers += 1
                _p.unlock()
            progress = 1.0 - numDirtyLayers/float(self._numLayers)
            self._dirtyIndicator.setTileProgress(tileId, progress) 
                    
