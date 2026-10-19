package com.example;

/**
 * Main application class.
 */
public class App {
    private String name;
    private int count;

    public App(String name) {
        this.name = name;
        this.count = 0;
    }

    public String greet() {
        return "Hello, " + name + "!";
    }

    public void increment() {
        count++;
    }

    public int getCount() {
        return count;
    }

    public static void main(String[] args) {
        App app = new App("World");
        System.out.println(app.greet());
        app.increment();
        System.out.println("Count: " + app.getCount());
    }
}
