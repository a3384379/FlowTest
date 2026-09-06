package com.flowtest.golden;

public interface OrderService {
    OrderDto create(CreateOrderRequest request);

    OrderDto find(String id);
}

record CreateOrderRequest(String productId, int quantity) {}

record OrderDto(String id, String status) {}
