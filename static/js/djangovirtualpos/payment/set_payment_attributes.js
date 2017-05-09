$(document).ready(function(){

	/** Muestra un mensaje de error */

	function show_error(message){

		console.log(message);

		if(PNotify){
			 $(function(){
				new PNotify({
					title: 'Error',
					text: message,
					type: 'error',
					desktop: {
						desktop: true
					}
				});
			 });
		}
	}


	/********************************************************************/
	/* Pago compra */
	$(".pay_button").click(function(event){

		$(".pay_button").attr("disabled", true);
		$(".pay_button").addClass("disabled");


		var $this = $(this);
		var url = vpos_constants.get("SET_PAYMENT_ATTRIBUTES_URL");
		var $form = $(this).parents("form");
		var post = {
			payment_code: vpos_constants.get("PAYMENT_CODE"),
			url_ok: vpos_constants.get("URL_OK"),
			url_nok: vpos_constants.get("URL_NOK"),
			tpv_id: $(this).attr("id").replace("tpv_button_","")

		};


		// Evitar que se pueda pulsar más de una vez sobre el botón
		if(this.clicked){
			event.preventDefault();
			return;
		}
		else{
				this.clicked = true;
		}

		$this.addClass("waiting");

		$.post(url, post, function(data){
			var $input;

			if("status" in data && data["status"]=="error"){
				show_error("No se ha podido generar el número de operación");
				return false;
			}

			var formdata = data['data'];

			// Para cada atributo generado por el servidor devuelto,
			// lo asignamos.
			// Esto incluye el número de operación y la firma
			// y cualquier otro atributo generado.
			$form.attr({
				"action": data['action'],
				"method": data['method']
			});

			if(data['enctype']){
				$form.attr("enctype", data['enctype']);
			}

			for (name in formdata) {
				$input = $('<input type="hidden" />');
				$input.attr("name", name).val(formdata[name]);
				$form.append($input);
			}

			// Enviamos el formulario

			// No enviamos formulario "por el momento".
			$form.submit();

			return false;
		});
		return false;
	});

	/********************************************************************/

});
