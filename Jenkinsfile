#!groovy
timestamps {
    node {
        checkout scm
        docker.withRegistry('https://registry.5gex:5000') {
            def image = docker.build("tnova-connector:1.0.0.${env.BUILD_NUMBER}")
            image.push()
            image.push('latest')
        }
    }
}