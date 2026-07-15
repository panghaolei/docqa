package com.docqa.controller;

import com.docqa.dto.ApiResult;
import com.docqa.dto.LoginRequest;
import com.docqa.dto.LoginResponse;
import com.docqa.service.UserService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/user")
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @PostMapping("/login")
    public ApiResult<LoginResponse> login(@RequestBody LoginRequest req) {
        return ApiResult.success(userService.login(req.getUsername()));
    }
}
