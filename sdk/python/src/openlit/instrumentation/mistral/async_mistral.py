"""
Module for monitoring Mistral API calls.
"""

import logging
import time
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.sdk.resources import SERVICE_NAME, TELEMETRY_SDK_NAME, DEPLOYMENT_ENVIRONMENT
from openlit.__helpers import (
    get_chat_model_cost,
    get_embed_model_cost,
    handle_exception,
    response_as_dict,
    calculate_ttft,
    calculate_tbt,
    create_metrics_attributes,
    set_server_address_and_port
)
from openlit.semcov import SemanticConvention

# Initialize logger for logging potential issues and operations
logger = logging.getLogger(__name__)

def async_chat(version, environment, application_name, tracer,
         pricing_info, capture_message_content, metrics, disable_metrics):
    """
    Generates a telemetry wrapper for chat to collect metrics.

    Args:
        version: Version of the monitoring package.
        environment: Deployment environment (e.g., production, staging).
        application_name: Name of the application using the Mistral API.
        tracer: OpenTelemetry tracer for creating spans.
        pricing_info: Information used for calculating the cost of Mistral usage.
        capture_message_content: Flag indicating whether to trace the actual content.

    Returns:
        A function that wraps the chat method to add telemetry.
    """

    async def wrapper(wrapped, instance, args, kwargs):
        """
        Wraps the 'chat' API call to add telemetry.
        
        This collects metrics such as execution time, cost, and token usage, and handles errors
        gracefully, adding details to the trace for observability.

        Args:
            wrapped: The original 'chat' method to be wrapped.
            instance: The instance of the class where the original method is defined.
            args: Positional arguments for the 'chat' method.
            kwargs: Keyword arguments for the 'chat' method.

        Returns:
            The response from the original 'chat' method.
        """

        server_address, server_port = set_server_address_and_port(instance, 'api.mistral.ai', 443)
        request_model = kwargs.get('model', 'mistral-small-latest')

        span_name = f'{SemanticConvention.GEN_AI_OPERATION_TYPE_CHAT} {request_model}'

        with tracer.start_as_current_span(span_name, kind=SpanKind.CLIENT) as span:
            start_time = time.time()
            response = await wrapped(*args, **kwargs)
            end_time = time.time()

            response_dict = response_as_dict(response)

            try:
                # Format 'messages' into a single string
                message_prompt = kwargs.get('messages', '')
                formatted_messages = []
                for message in message_prompt:
                    role = message['role']
                    content = message['content']

                    if isinstance(content, list):
                        content_str = ", ".join(
                            f'{item["type"]}: {item["text"] if "text" in item else item["image_url"]}'
                            if "type" in item else f'text: {item["text"]}'
                            for item in content
                        )
                        formatted_messages.append(f'{role}: {content_str}')
                    else:
                        formatted_messages.append(f'{role}: {content}')
                prompt = '\n'.join(formatted_messages)

                input_tokens = response_dict.get('usage').get('prompt_tokens')
                output_tokens = response_dict.get('usage').get('completion_tokens')

                # Calculate cost of the operation
                cost = get_chat_model_cost(request_model,
                                            pricing_info, input_tokens,
                                            output_tokens)

                # Set base span attribues (OTel Semconv)
                span.set_attribute(TELEMETRY_SDK_NAME, 'openlit')
                span.set_attribute(SemanticConvention.GEN_AI_OPERATION,
                                    SemanticConvention.GEN_AI_OPERATION_TYPE_CHAT)
                span.set_attribute(SemanticConvention.GEN_AI_SYSTEM,
                                    SemanticConvention.GEN_AI_SYSTEM_MISTRAL)
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_MODEL,
                                    request_model)
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_SEED,
                                    kwargs.get('seed', ''))
                span.set_attribute(SemanticConvention.SERVER_PORT,
                                    server_port)
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_FREQUENCY_PENALTY,
                                    kwargs.get('frequency_penalty', 0.0))
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_MAX_TOKENS,
                                    kwargs.get('max_tokens', -1))
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_PRESENCE_PENALTY,
                                    kwargs.get('presence_penalty', 0.0))
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_STOP_SEQUENCES,
                                    kwargs.get('stop', []))
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_TEMPERATURE,
                                    kwargs.get('temperature', 1.0))
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_TOP_P,
                                    kwargs.get('top_p', 1.0))
                span.set_attribute(SemanticConvention.GEN_AI_RESPONSE_ID,
                                    response_dict.get('id'))
                span.set_attribute(SemanticConvention.GEN_AI_RESPONSE_MODEL,
                                    response_dict.get('model'))
                span.set_attribute(SemanticConvention.GEN_AI_USAGE_INPUT_TOKENS,
                                    input_tokens)
                span.set_attribute(SemanticConvention.GEN_AI_USAGE_OUTPUT_TOKENS,
                                    output_tokens)
                span.set_attribute(SemanticConvention.SERVER_ADDRESS,
                                    server_address)

                # Set base span attribues (Extras)
                span.set_attribute(DEPLOYMENT_ENVIRONMENT,
                                    environment)
                span.set_attribute(SERVICE_NAME,
                                    application_name)
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_IS_STREAM,
                                    False)
                span.set_attribute(SemanticConvention.GEN_AI_USAGE_TOTAL_TOKENS,
                                    input_tokens + output_tokens)
                span.set_attribute(SemanticConvention.GEN_AI_USAGE_COST,
                                    cost)
                span.set_attribute(SemanticConvention.GEN_AI_SERVER_TTFT,
                                    end_time - start_time)
                span.set_attribute(SemanticConvention.GEN_AI_SDK_VERSION,
                                    version)
                if capture_message_content:
                    span.add_event(
                        name=SemanticConvention.GEN_AI_CONTENT_PROMPT_EVENT,
                        attributes={
                            SemanticConvention.GEN_AI_CONTENT_PROMPT: prompt,
                        },
                    )

                for i in range(kwargs.get('n',1)):
                    span.set_attribute(SemanticConvention.GEN_AI_RESPONSE_FINISH_REASON,
                                        [response_dict.get('choices')[i].get('finish_reason')])
                    if capture_message_content:
                        span.add_event(
                            name=SemanticConvention.GEN_AI_CONTENT_COMPLETION_EVENT,
                            attributes={
                                # pylint: disable=line-too-long
                                SemanticConvention.GEN_AI_CONTENT_COMPLETION: str(response_dict.get('choices')[i].get('message').get('content')),
                            },
                        )
                    if kwargs.get('tools'):
                        span.set_attribute(SemanticConvention.GEN_AI_TOOL_CALLS,
                                        str(response_dict.get('choices')[i].get('message').get('tool_calls')))

                    if isinstance(response_dict.get('choices')[i].get('message').get('content'), str):
                        span.set_attribute(SemanticConvention.GEN_AI_OUTPUT_TYPE,
                                        'text')
                    elif response_dict.get('choices')[i].get('message').get('content') is not None:
                        span.set_attribute(SemanticConvention.GEN_AI_OUTPUT_TYPE,
                                        'json')

                span.set_status(Status(StatusCode.OK))

                if disable_metrics is False:
                    attributes = create_metrics_attributes(
                        service_name=application_name,
                        deployment_environment=environment,
                        operation=SemanticConvention.GEN_AI_OPERATION_TYPE_CHAT,
                        system=SemanticConvention.GEN_AI_SYSTEM_MISTRAL,
                        request_model=request_model,
                        server_address=server_address,
                        server_port=server_port,
                        response_model=response_dict.get('model'),
                    )

                    metrics['genai_client_usage_tokens'].record(
                        input_tokens + output_tokens, attributes
                    )
                    metrics['genai_client_operation_duration'].record(
                        end_time - start_time, attributes
                    )
                    metrics['genai_server_ttft'].record(
                        end_time - start_time, attributes
                    )
                    metrics['genai_requests'].add(1, attributes)
                    metrics['genai_completion_tokens'].add(output_tokens, attributes)
                    metrics['genai_prompt_tokens'].add(input_tokens, attributes)
                    metrics['genai_cost'].record(cost, attributes)

                # Return original response
                return response

            except Exception as e:
                handle_exception(span, e)
                logger.error('Error in trace creation: %s', e)

                # Return original response
                return response

    return wrapper

def async_chat_stream(version, environment, application_name,
                tracer, pricing_info, capture_message_content, metrics, disable_metrics):
    """
    Generates a telemetry wrapper for chat_stream to collect metrics.

    Args:
        version: Version of the monitoring package.
        environment: Deployment environment (e.g., production, staging).
        application_name: Name of the application using the Mistral API.
        tracer: OpenTelemetry tracer for creating spans.
        pricing_info: Information used for calculating the cost of Mistral usage.
        capture_message_content: Flag indicating whether to trace the actual content.

    Returns:
        A function that wraps the chat method to add telemetry.
    """

    async def wrapper(wrapped, instance, args, kwargs):
        """
        Wraps the 'chat_stream' API call to add telemetry.
        
        This collects metrics such as execution time, cost, and token usage, and handles errors
        gracefully, adding details to the trace for observability.

        Args:
            wrapped: The original 'chat_stream' method to be wrapped.
            instance: The instance of the class where the original method is defined.
            args: Positional arguments for the 'chat_stream' method.
            kwargs: Keyword arguments for the 'chat_stream' method.

        Returns:
            The response from the original 'chat_stream' method.
        """

        class TracedAsyncStream:
            """
            Wrapper for streaming responses to collect metrics and trace data.
            Wraps the 'mistral.syncStream' response to collect message IDs and aggregated response.

            This class implements the '__aiter__' and '__anext__' methods that
            handle asynchronous streaming responses.

            This class also implements '__aenter__' and '__aexit__' methods that
            handle asynchronous context management protocol.
            """
            def __init__(
                    self,
                    wrapped,
                    span,
                    kwargs,
                    server_address,
                    server_port,
                    **args,
                ):
                self.__wrapped__ = wrapped
                self._span = span
                # Placeholder for aggregating streaming response
                self._llmresponse = ''
                self._response_id = ''
                self._response_model = ''
                self._finish_reason = ''
                self._input_tokens = ''
                self._output_tokens = ''

                self._args = args
                self._kwargs = kwargs
                self._start_time = time.time()
                self._end_time = None
                self._timestamps = []
                self._ttft = 0
                self._tbt = 0
                self._server_address = server_address
                self._server_port = server_port

            async def __aenter__(self):
                await self.__wrapped__.__aenter__()
                return self

            async def __aexit__(self, exc_type, exc_value, traceback):
                await self.__wrapped__.__aexit__(exc_type, exc_value, traceback)

            def __aiter__(self):
                return self

            async def __getattr__(self, name):
                """Delegate attribute access to the wrapped object."""
                return getattr(await self.__wrapped__, name)

            async def __anext__(self):
                try:
                    chunk = await self.__wrapped__.__anext__()
                    end_time = time.time()
                    # Record the timestamp for the current chunk
                    self._timestamps.append(end_time)

                    if len(self._timestamps) == 1:
                        # Calculate time to first chunk
                        self._ttft = calculate_ttft(self._timestamps, self._start_time)

                    chunked = response_as_dict(chunk)

                    self._llmresponse += chunked.get('data').get('choices')[0].get('delta').get('content')
                    if chunked.get('data').get('usage') is not None:
                        self._response_id = chunked.get('data').get('id')
                        self._response_model = chunked.get('data').get('model')
                        self._input_tokens = chunked.get('data').get('usage').get('prompt_tokens')
                        self._output_tokens = chunked.get('data').get('usage').get('completion_tokens')
                        self._finish_reason = chunked.get('data').get('choices')[0].get('finish_reason')

                    return chunk
                except StopAsyncIteration:
                    # Handling exception ensure observability without disrupting operation
                    try:
                        self._end_time = time.time()
                        if len(self._timestamps) > 1:
                            self._tbt = calculate_tbt(self._timestamps)

                        # Format 'messages' into a single string
                        message_prompt = self._kwargs.get('messages', '')
                        formatted_messages = []
                        for message in message_prompt:
                            role = message['role']
                            content = message['content']

                            if isinstance(content, list):
                                content_str_list = []
                                for item in content:
                                    if item['type'] == 'text':
                                        content_str_list.append(f'text: {item["text"]}')
                                    elif (item['type'] == 'image_url' and
                                        not item['image_url']['url'].startswith('data:')):
                                        content_str_list.append(f'image_url: {item["image_url"]["url"]}')
                                content_str = ", ".join(content_str_list)
                                formatted_messages.append(f'{role}: {content_str}')
                            else:
                                formatted_messages.append(f'{role}: {content}')
                        prompt = '\n'.join(formatted_messages)

                        request_model = self._kwargs.get('model', 'mistral-small-latest')

                        # Calculate cost of the operation
                        cost = get_chat_model_cost(request_model,
                                                    pricing_info, self._input_tokens,
                                                    self._output_tokens)

                        # Set Span attributes (OTel Semconv)
                        self._span.set_attribute(TELEMETRY_SDK_NAME, 'openlit')
                        self._span.set_attribute(SemanticConvention.GEN_AI_OPERATION,
                                            SemanticConvention.GEN_AI_OPERATION_TYPE_CHAT)
                        self._span.set_attribute(SemanticConvention.GEN_AI_SYSTEM,
                                            SemanticConvention.GEN_AI_SYSTEM_MISTRAL)
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_MODEL,
                                            request_model)
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_SEED,
                                            self._kwargs.get('seed', ''))
                        self._span.set_attribute(SemanticConvention.SERVER_PORT,
                                            self._server_port)
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_FREQUENCY_PENALTY,
                                            self._kwargs.get('frequency_penalty', 0.0))
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_MAX_TOKENS,
                                            self._kwargs.get('max_tokens', -1))
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_PRESENCE_PENALTY,
                                            self._kwargs.get('presence_penalty', 0.0))
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_STOP_SEQUENCES,
                                            self._kwargs.get('stop_sequences', []))
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_TEMPERATURE,
                                            self._kwargs.get('temperature', 0.3))
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_TOP_K,
                                            self._kwargs.get('k', 1.0))
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_TOP_P,
                                            self._kwargs.get('p', 1.0))
                        self._span.set_attribute(SemanticConvention.GEN_AI_RESPONSE_FINISH_REASON,
                                            [self._finish_reason])
                        self._span.set_attribute(SemanticConvention.GEN_AI_RESPONSE_ID,
                                            self._response_id)
                        self._span.set_attribute(SemanticConvention.GEN_AI_RESPONSE_MODEL,
                                            self._response_model)
                        self._span.set_attribute(SemanticConvention.GEN_AI_USAGE_INPUT_TOKENS,
                                            self._input_tokens)
                        self._span.set_attribute(SemanticConvention.GEN_AI_USAGE_OUTPUT_TOKENS,
                                            self._output_tokens)
                        self._span.set_attribute(SemanticConvention.SERVER_ADDRESS,
                                            self._server_address)

                        if isinstance(self._llmresponse, str):
                            self._span.set_attribute(SemanticConvention.GEN_AI_OUTPUT_TYPE,
                                            'text')
                        else:
                            self._span.set_attribute(SemanticConvention.GEN_AI_OUTPUT_TYPE,
                                            'json')

                        # Set Span attributes (Extra)
                        self._span.set_attribute(DEPLOYMENT_ENVIRONMENT,
                                            environment)
                        self._span.set_attribute(SERVICE_NAME,
                                            application_name)
                        self._span.set_attribute(SemanticConvention.GEN_AI_REQUEST_IS_STREAM,
                                            True)
                        self._span.set_attribute(SemanticConvention.GEN_AI_USAGE_TOTAL_TOKENS,
                                            self._input_tokens + self._output_tokens)
                        self._span.set_attribute(SemanticConvention.GEN_AI_USAGE_COST,
                                            cost)
                        self._span.set_attribute(SemanticConvention.GEN_AI_SERVER_TBT,
                                            self._tbt)
                        self._span.set_attribute(SemanticConvention.GEN_AI_SERVER_TTFT,
                                            self._ttft)
                        self._span.set_attribute(SemanticConvention.GEN_AI_SDK_VERSION,
                                            version)
                        if capture_message_content:
                            self._span.add_event(
                                name=SemanticConvention.GEN_AI_CONTENT_PROMPT_EVENT,
                                attributes={
                                    SemanticConvention.GEN_AI_CONTENT_PROMPT: prompt,
                                },
                            )
                            self._span.add_event(
                                name=SemanticConvention.GEN_AI_CONTENT_COMPLETION_EVENT,
                                attributes={
                                    SemanticConvention.GEN_AI_CONTENT_COMPLETION: self._llmresponse,
                                },
                            )
                        self._span.set_status(Status(StatusCode.OK))

                        if disable_metrics is False:
                            attributes = create_metrics_attributes(
                                service_name=application_name,
                                deployment_environment=environment,
                                operation=SemanticConvention.GEN_AI_OPERATION_TYPE_CHAT,
                                system=SemanticConvention.GEN_AI_SYSTEM_MISTRAL,
                                request_model=request_model,
                                server_address=self._server_address,
                                server_port=self._server_port,
                                response_model=self._response_model,
                            )

                            metrics['genai_client_usage_tokens'].record(
                                self._input_tokens + self._output_tokens, attributes
                            )
                            metrics['genai_client_operation_duration'].record(
                                self._end_time - self._start_time, attributes
                            )
                            metrics['genai_server_tbt'].record(
                                self._tbt, attributes
                            )
                            metrics['genai_server_ttft'].record(
                                self._ttft, attributes
                            )
                            metrics['genai_requests'].add(1, attributes)
                            metrics['genai_completion_tokens'].add(self._output_tokens, attributes)
                            metrics['genai_prompt_tokens'].add(self._input_tokens, attributes)
                            metrics['genai_cost'].record(cost, attributes)

                    except Exception as e:
                        handle_exception(self._span, e)
                        logger.error('Error in trace creation: %s', e)
                    finally:
                        self._span.end()
                    raise

        server_address, server_port = set_server_address_and_port(instance, 'api.mistral.ai', 443)
        request_model = kwargs.get('model', 'mistral-small-latest')

        span_name = f'{SemanticConvention.GEN_AI_OPERATION_TYPE_CHAT} {request_model}'

        awaited_wrapped = await wrapped(*args, **kwargs)
        span = tracer.start_span(span_name, kind=SpanKind.CLIENT)
        return TracedAsyncStream(awaited_wrapped, span, kwargs, server_address, server_port)

    return wrapper

def async_embeddings(version, environment, application_name,
              tracer, pricing_info, capture_message_content, metrics, disable_metrics):
    """
    Generates a telemetry wrapper for embeddings to collect metrics.
    
    Args:
        version: Version of the monitoring package.
        environment: Deployment environment (e.g., production, staging).
        application_name: Name of the application using the Mistral API.
        tracer: OpenTelemetry tracer for creating spans.
        pricing_info: Information used for calculating the cost of Mistral usage.
        capture_message_content: Flag indicating whether to trace the actual content.
    
    Returns:
        A function that wraps the embeddings method to add telemetry.
    """

    def wrapper(wrapped, instance, args, kwargs):
        """
        Wraps the 'embeddings' API call to add telemetry.

        This collects metrics such as execution time, cost, and token usage, and handles errors
        gracefully, adding details to the trace for observability.

        Args:
            wrapped: The original 'embeddings' method to be wrapped.
            instance: The instance of the class where the original method is defined.
            args: Positional arguments for the 'embeddings' method.
            kwargs: Keyword arguments for the 'embeddings' method.

        Returns:
            The response from the original 'embeddings' method.
        """

        server_address, server_port = set_server_address_and_port(instance, 'api.mistral.ai', 443)
        request_model = kwargs.get('model', 'mistral-embed')

        span_name = f'{SemanticConvention.GEN_AI_OPERATION_TYPE_EMBEDDING} {request_model}'

        with tracer.start_as_current_span(span_name, kind= SpanKind.CLIENT) as span:
            start_time = time.time()
            response = wrapped(*args, **kwargs)
            end_time = time.time()

            response_dict = response_as_dict(response)
            try:
                input_tokens = response_dict.get('usage').get('prompt_tokens')

                # Calculate cost of the operation
                cost = get_embed_model_cost(request_model,
                                    pricing_info, input_tokens)

                # Set Span attributes (OTel Semconv)
                span.set_attribute(TELEMETRY_SDK_NAME, 'openlit')
                span.set_attribute(SemanticConvention.GEN_AI_OPERATION,
                                    SemanticConvention.GEN_AI_OPERATION_TYPE_EMBEDDING)
                span.set_attribute(SemanticConvention.GEN_AI_SYSTEM,
                                    SemanticConvention.GEN_AI_SYSTEM_MISTRAL)
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_MODEL,
                                    request_model)
                span.set_attribute(SemanticConvention.GEN_AI_REQUEST_ENCODING_FORMATS,
                                    [kwargs.get('encoding_format', 'float')])
                span.set_attribute(SemanticConvention.GEN_AI_RESPONSE_MODEL,
                                    response_dict.get('model'))
                span.set_attribute(SemanticConvention.SERVER_ADDRESS,
                                    server_address)
                span.set_attribute(SemanticConvention.SERVER_PORT,
                                    server_port)
                span.set_attribute(SemanticConvention.GEN_AI_USAGE_INPUT_TOKENS,
                                    input_tokens)

                # Set Span attributes (Extras)
                span.set_attribute(DEPLOYMENT_ENVIRONMENT,
                                    environment)
                span.set_attribute(SERVICE_NAME,
                                    application_name)
                span.set_attribute(SemanticConvention.GEN_AI_USAGE_TOTAL_TOKENS,
                                    input_tokens)
                span.set_attribute(SemanticConvention.GEN_AI_USAGE_COST,
                                    cost)
                span.set_attribute(SemanticConvention.GEN_AI_SDK_VERSION,
                                    version)

                if capture_message_content:
                    span.add_event(
                        name=SemanticConvention.GEN_AI_CONTENT_PROMPT_EVENT,
                        attributes={
                            SemanticConvention.GEN_AI_CONTENT_PROMPT: str(kwargs.get('inputs', '')),
                        },
                    )

                span.set_status(Status(StatusCode.OK))

                if disable_metrics is False:
                    attributes = create_metrics_attributes(
                        service_name=application_name,
                        deployment_environment=environment,
                        operation=SemanticConvention.GEN_AI_OPERATION_TYPE_EMBEDDING,
                        system=SemanticConvention.GEN_AI_SYSTEM_MISTRAL,
                        request_model=request_model,
                        server_address=server_address,
                        server_port=server_port,
                        response_model=response_dict.get('model'),
                    )
                    metrics['genai_client_usage_tokens'].record(
                            input_tokens, attributes
                        )
                    metrics['genai_client_operation_duration'].record(
                        end_time - start_time, attributes
                    )
                    metrics['genai_requests'].add(1, attributes)
                    metrics['genai_prompt_tokens'].add(input_tokens, attributes)
                    metrics['genai_cost'].record(cost, attributes)

                # Return original response
                return response

            except Exception as e:
                handle_exception(span, e)
                logger.error('Error in trace creation: %s', e)

                # Return original response
                return response

    return wrapper
