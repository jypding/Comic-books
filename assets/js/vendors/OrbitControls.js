console.warn( "THREE.OrbitControls: As part of the transition to ES6 Modules, the files in 'examples/js' were deprecated in May 2020 (r117) and will be deleted in December 2020 (r124). You can find more information about developing using ES6 Modules in https://threejs.org/docs/#manual/en/introduction/Installation." );

THREE.OrbitControls = function ( object, domElement ) {
	if ( domElement === undefined ) console.warn( 'THREE.OrbitControls: The second parameter "domElement" is now mandatory.' );
	this.object = object;
	this.domElement = domElement;
	this.enabled = true;
	this.target = new THREE.Vector3();
	this.minDistance = 0;
	this.maxDistance = Infinity;
	this.minZoom = 0;
	this.maxZoom = Infinity;
	this.minPolarAngle = 0;
	this.maxPolarAngle = Math.PI;
	this.minAzimuthAngle = - Infinity;
	this.maxAzimuthAngle = Infinity;
	this.enableDamping = false;
	this.dampingFactor = 0.05;
	this.enableZoom = true;
	this.zoomSpeed = 1.0;
	this.enableRotate = true;
	this.rotateSpeed = 1.0;
	this.enablePan = true;
	this.panSpeed = 1.0;
	this.screenSpacePanning = true;
	this.keyPanSpeed = 7.0;
	this.autoRotate = false;
	this.autoRotateSpeed = 2.0;
	this.enableKeys = true;
	this.keys = { LEFT: 37, UP: 38, RIGHT: 39, BOTTOM: 40 };
	this.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
	this.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };

	var scope = this;
	var changeEvent = { type: 'change' };
	var startEvent = { type: 'start' };
	var endEvent = { type: 'end' };
	var STATE = { NONE: - 1, ROTATE: 0, DOLLY: 1, PAN: 2, TOUCH_ROTATE: 3, TOUCH_PAN: 4, TOUCH_DOLLY_PAN: 5, TOUCH_DOLLY_ROTATE: 6 };
	var state = STATE.NONE;
	var EPS = 0.000001;
	var spherical = new THREE.Spherical();
	var sphericalDelta = new THREE.Spherical();
	var scale = 1;
	var panOffset = new THREE.Vector3();
	var zoomChanged = false;
	var rotateStart = new THREE.Vector2();
	var rotateEnd = new THREE.Vector2();
	var rotateDelta = new THREE.Vector2();
	var panStart = new THREE.Vector2();
	var panEnd = new THREE.Vector2();
	var panDelta = new THREE.Vector2();
	var dollyStart = new THREE.Vector2();
	var dollyEnd = new THREE.Vector2();
	var dollyDelta = new THREE.Vector2();

	function getAutoRotationAngle() { return 2 * Math.PI / 60 / 60 * scope.autoRotateSpeed; }
	function getZoomScale() { return Math.pow( 0.95, scope.zoomSpeed ); }
	function rotateLeft( angle ) { sphericalDelta.theta -= angle; }
	function rotateUp( angle ) { sphericalDelta.phi -= angle; }

	var panLeft = function () {
		var v = new THREE.Vector3();
		return function panLeft( distance, objectMatrix ) {
			v.setFromMatrixColumn( objectMatrix, 0 );
			v.multiplyScalar( - distance );
			panOffset.add( v );
		};
	}();

	var panUp = function () {
		var v = new THREE.Vector3();
		return function panUp( distance, objectMatrix ) {
			if ( scope.screenSpacePanning === true ) {
				v.setFromMatrixColumn( objectMatrix, 1 );
			} else {
				v.setFromMatrixColumn( objectMatrix, 0 );
				v.crossVectors( scope.object.up, v );
			}
			v.multiplyScalar( distance );
			panOffset.add( v );
		};
	}();

	var pan = function () {
		var offset = new THREE.Vector3();
		return function pan( deltaX, deltaY ) {
			var element = scope.domElement;
			if ( scope.object.isPerspectiveCamera ) {
				var position = scope.object.position;
				offset.copy( position ).sub( scope.target );
				var targetDistance = offset.length();
				targetDistance *= Math.tan( ( scope.object.fov / 2 ) * Math.PI / 180.0 );
				panLeft( 2 * deltaX * targetDistance / element.clientHeight, scope.object.matrix );
				panUp( 2 * deltaY * targetDistance / element.clientHeight, scope.object.matrix );
			} else if ( scope.object.isOrthographicCamera ) {
				panLeft( deltaX * ( scope.object.right - scope.object.left ) / scope.object.zoom / element.clientWidth, scope.object.matrix );
				panUp( deltaY * ( scope.object.top - scope.object.bottom ) / scope.object.zoom / element.clientHeight, scope.object.matrix );
			}
		};
	}();

	function dollyOut( dollyScale ) {
		if ( scope.object.isPerspectiveCamera ) {
			scale /= dollyScale;
		} else if ( scope.object.isOrthographicCamera ) {
			scope.object.zoom = Math.max( scope.minZoom, Math.min( scope.maxZoom, scope.object.zoom * dollyScale ) );
			scope.object.updateProjectionMatrix();
			zoomChanged = true;
		}
	}

	function dollyIn( dollyScale ) {
		if ( scope.object.isPerspectiveCamera ) {
			scale *= dollyScale;
		} else if ( scope.object.isOrthographicCamera ) {
			scope.object.zoom = Math.max( scope.minZoom, Math.min( scope.maxZoom, scope.object.zoom / dollyScale ) );
			scope.object.updateProjectionMatrix();
			zoomChanged = true;
		}
	}

	this.update = function () {
		var offset = new THREE.Vector3();
		var quat = new THREE.Quaternion().setFromUnitVectors( object.up, new THREE.Vector3( 0, 1, 0 ) );
		var quatInverse = quat.clone().invert ? quat.clone().invert() : quat.clone().inverse();
		var lastPosition = new THREE.Vector3();
		var lastQuaternion = new THREE.Quaternion();
		var twoPI = 2 * Math.PI;

		return function update() {
			var position = scope.object.position;
			offset.copy( position ).sub( scope.target );
			offset.applyQuaternion( quat );
			spherical.setFromVector3( offset );
			if ( scope.autoRotate && state === STATE.NONE ) rotateLeft( getAutoRotationAngle() );
			if ( scope.enableDamping ) {
				spherical.theta += sphericalDelta.theta * scope.dampingFactor;
				spherical.phi += sphericalDelta.phi * scope.dampingFactor;
			} else {
				spherical.theta += sphericalDelta.theta;
				spherical.phi += sphericalDelta.phi;
			}
			var min = scope.minAzimuthAngle;
			var max = scope.maxAzimuthAngle;
			if ( isFinite( min ) && isFinite( max ) ) {
				if ( min < - Math.PI ) min += twoPI; else if ( min > Math.PI ) min -= twoPI;
				if ( max < - Math.PI ) max += twoPI; else if ( max > Math.PI ) max -= twoPI;
				if ( min < max ) spherical.theta = Math.max( min, Math.min( max, spherical.theta ) );
				else spherical.theta = ( spherical.theta > ( min + max ) / 2 ) ? Math.max( min, spherical.theta ) : Math.min( max, spherical.theta );
			}
			spherical.phi = Math.max( scope.minPolarAngle, Math.min( scope.maxPolarAngle, spherical.phi ) );
			spherical.makeSafe();
			spherical.radius *= scale;
			spherical.radius = Math.max( scope.minDistance, Math.min( scope.maxDistance, spherical.radius ) );
			if ( scope.enableDamping === true ) scope.target.addScaledVector( panOffset, scope.dampingFactor );
			else scope.target.add( panOffset );
			offset.setFromSpherical( spherical );
			offset.applyQuaternion( quatInverse );
			position.copy( scope.target ).add( offset );
			scope.object.lookAt( scope.target );
			if ( scope.enableDamping === true ) {
				sphericalDelta.theta *= ( 1 - scope.dampingFactor );
				sphericalDelta.phi *= ( 1 - scope.dampingFactor );
				panOffset.multiplyScalar( 1 - scope.dampingFactor );
			} else {
				sphericalDelta.set( 0, 0, 0 );
				panOffset.set( 0, 0, 0 );
			}
			scale = 1;
			if ( zoomChanged || lastPosition.distanceToSquared( scope.object.position ) > EPS || 8 * ( 1 - lastQuaternion.dot( scope.object.quaternion ) ) > EPS ) {
				scope.dispatchEvent( changeEvent );
				lastPosition.copy( scope.object.position );
				lastQuaternion.copy( scope.object.quaternion );
				zoomChanged = false;
				return true;
			}
			return false;
		};
	}();

	function onPointerDown( event ) {
		if ( scope.enabled === false ) return;
		if ( event.pointerType === 'mouse' ) onMouseDown( event );
	}
	function onPointerMove( event ) {
		if ( scope.enabled === false ) return;
		if ( event.pointerType === 'mouse' ) onMouseMove( event );
	}
	function onPointerUp( event ) {
		if ( scope.enabled === false ) return;
		if ( event.pointerType === 'mouse' ) onMouseUp( event );
	}

	function onMouseDown( event ) {
		event.preventDefault();
		scope.domElement.focus ? scope.domElement.focus() : window.focus();
		var mouseAction;
		switch ( event.button ) {
			case 0: mouseAction = scope.mouseButtons.LEFT; break;
			case 1: mouseAction = scope.mouseButtons.MIDDLE; break;
			case 2: mouseAction = scope.mouseButtons.RIGHT; break;
			default: mouseAction = - 1;
		}
		switch ( mouseAction ) {
			case THREE.MOUSE.DOLLY: if ( scope.enableZoom === false ) return; state = STATE.DOLLY; handleMouseDownDolly( event ); break;
			case THREE.MOUSE.ROTATE:
				if ( event.ctrlKey || event.metaKey || event.shiftKey ) { if ( scope.enablePan === false ) return; state = STATE.PAN; handleMouseDownPan( event ); }
				else { if ( scope.enableRotate === false ) return; state = STATE.ROTATE; handleMouseDownRotate( event ); }
				break;
			case THREE.MOUSE.PAN:
				if ( event.ctrlKey || event.metaKey || event.shiftKey ) { if ( scope.enableRotate === false ) return; state = STATE.ROTATE; handleMouseDownRotate( event ); }
				else { if ( scope.enablePan === false ) return; state = STATE.PAN; handleMouseDownPan( event ); }
				break;
			default: state = STATE.NONE;
		}
		if ( state !== STATE.NONE ) {
			scope.domElement.ownerDocument.addEventListener( 'pointermove', onPointerMove, false );
			scope.domElement.ownerDocument.addEventListener( 'pointerup', onPointerUp, false );
			scope.dispatchEvent( startEvent );
		}
	}

	function onMouseMove( event ) {
		if ( scope.enabled === false ) return;
		event.preventDefault();
		switch ( state ) {
			case STATE.ROTATE: if ( scope.enableRotate === false ) return; handleMouseMoveRotate( event ); break;
			case STATE.DOLLY: if ( scope.enableZoom === false ) return; handleMouseMoveDolly( event ); break;
			case STATE.PAN: if ( scope.enablePan === false ) return; handleMouseMovePan( event ); break;
		}
	}

	function onMouseUp( event ) {
		if ( scope.enabled === false ) return;
		scope.domElement.ownerDocument.removeEventListener( 'pointermove', onPointerMove, false );
		scope.domElement.ownerDocument.removeEventListener( 'pointerup', onPointerUp, false );
		scope.dispatchEvent( endEvent );
		state = STATE.NONE;
	}

	function onMouseWheel( event ) {
		if ( scope.enabled === false || scope.enableZoom === false || ( state !== STATE.NONE && state !== STATE.ROTATE ) ) return;
		event.preventDefault();
		event.stopPropagation();
		scope.dispatchEvent( startEvent );
		if ( event.deltaY < 0 ) dollyIn( getZoomScale() );
		else if ( event.deltaY > 0 ) dollyOut( getZoomScale() );
		scope.update();
		scope.dispatchEvent( endEvent );
	}

	function handleMouseDownRotate( event ) { rotateStart.set( event.clientX, event.clientY ); }
	function handleMouseDownDolly( event ) { dollyStart.set( event.clientX, event.clientY ); }
	function handleMouseDownPan( event ) { panStart.set( event.clientX, event.clientY ); }
	function handleMouseMoveRotate( event ) {
		rotateEnd.set( event.clientX, event.clientY );
		rotateDelta.subVectors( rotateEnd, rotateStart ).multiplyScalar( scope.rotateSpeed );
		var element = scope.domElement;
		rotateLeft( 2 * Math.PI * rotateDelta.x / element.clientHeight );
		rotateUp( 2 * Math.PI * rotateDelta.y / element.clientHeight );
		rotateStart.copy( rotateEnd );
		scope.update();
	}
	function handleMouseMoveDolly( event ) {
		dollyEnd.set( event.clientX, event.clientY );
		dollyDelta.subVectors( dollyEnd, dollyStart );
		if ( dollyDelta.y > 0 ) dollyOut( getZoomScale() );
		else if ( dollyDelta.y < 0 ) dollyIn( getZoomScale() );
		dollyStart.copy( dollyEnd );
		scope.update();
	}
	function handleMouseMovePan( event ) {
		panEnd.set( event.clientX, event.clientY );
		panDelta.subVectors( panEnd, panStart ).multiplyScalar( scope.panSpeed );
		pan( panDelta.x, panDelta.y );
		panStart.copy( panEnd );
		scope.update();
	}

	scope.domElement.addEventListener( 'contextmenu', function(e){e.preventDefault();}, false );
	scope.domElement.addEventListener( 'pointerdown', onPointerDown, false );
	scope.domElement.addEventListener( 'wheel', onMouseWheel, false );
	if ( scope.domElement.tabIndex === - 1 ) scope.domElement.tabIndex = 0;
	this.update();
};

THREE.OrbitControls.prototype = Object.create( THREE.EventDispatcher.prototype );
THREE.OrbitControls.prototype.constructor = THREE.OrbitControls;
