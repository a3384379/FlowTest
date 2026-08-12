import asyncio
from collections.abc import AsyncIterator
from typing import Any

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message
from grpc_reflection.v1alpha import reflection

SERVICE_NAME = "flowtest.user.v1.UserService"


def build_contract() -> tuple[descriptor_pool.DescriptorPool, type[Message], type[Message]]:
    file_descriptor = descriptor_pb2.FileDescriptorProto(
        name="flowtest/user/v1/user.proto",
        package="flowtest.user.v1",
        syntax="proto3",
    )
    request = file_descriptor.message_type.add(name="GetUserRequest")
    request.field.add(
        name="id",
        number=1,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    )
    reply = file_descriptor.message_type.add(name="GetUserReply")
    reply.field.add(
        name="id",
        number=1,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    )
    reply.field.add(
        name="name",
        number=2,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    )
    service = file_descriptor.service.add(name="UserService")
    service.method.add(
        name="GetUser",
        input_type=".flowtest.user.v1.GetUserRequest",
        output_type=".flowtest.user.v1.GetUserReply",
    )
    service.method.add(
        name="WatchUsers",
        input_type=".flowtest.user.v1.GetUserRequest",
        output_type=".flowtest.user.v1.GetUserReply",
        server_streaming=True,
    )
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(file_descriptor.SerializeToString())  # type: ignore[no-untyped-call]
    request_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName(  # type: ignore[no-untyped-call]
            "flowtest.user.v1.GetUserRequest"
        )
    )
    reply_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName(  # type: ignore[no-untyped-call]
            "flowtest.user.v1.GetUserReply"
        )
    )
    return pool, request_class, reply_class


async def serve() -> None:
    pool, request_class, reply_class = build_contract()

    def reply(identifier: str, name: str) -> Message:
        response = reply_class()
        response.id = identifier  # type: ignore[attr-defined]
        response.name = name  # type: ignore[attr-defined]
        return response

    def request_id(request: Message) -> str:
        value: Any = getattr(request, "id", "")
        return value if isinstance(value, str) else ""

    def serialize(value: Message) -> bytes:
        return value.SerializeToString()

    async def get_user(request: Message, context: grpc.aio.ServicerContext) -> Message:
        del context
        return reply(request_id(request) or "user-001", "测试用户")

    async def watch_users(
        request: Message,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[Message]:
        del context
        for index in range(3):
            yield reply(
                request_id(request) or f"user-{index + 1:03}",
                f"测试用户 {index + 1}",
            )

    server = grpc.aio.server(
        options=(
            ("grpc.max_send_message_length", 4 * 1024 * 1024),
            ("grpc.max_receive_message_length", 4 * 1024 * 1024),
        )
    )
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                SERVICE_NAME,
                {
                    "GetUser": grpc.unary_unary_rpc_method_handler(
                        get_user,
                        request_deserializer=request_class.FromString,
                        response_serializer=serialize,
                    ),
                    "WatchUsers": grpc.unary_stream_rpc_method_handler(
                        watch_users,
                        request_deserializer=request_class.FromString,
                        response_serializer=serialize,
                    ),
                },
            ),
        )
    )
    reflection.enable_server_reflection((SERVICE_NAME, reflection.SERVICE_NAME), server, pool=pool)
    server.add_insecure_port("[::]:50051")
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
